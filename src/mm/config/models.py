"""Pydantic models for every config file. Unknown keys are rejected so typos fail loudly."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mm.core.types import Mode, Product


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VenuePermission(_Strict):
    """What a jurisdiction allows on one venue. Everything defaults to off."""

    read: bool = False
    spot: bool = False
    perps: bool = False
    futures: bool = False
    options: bool = False
    stocks: bool = False
    etfs: bool = False
    prediction: bool = False
    intraday_equity: bool = False
    mode: str | None = None  # e.g. "nri" or "resident" for Indian brokers
    note: str = ""

    def allows(self, product: Product) -> bool:
        return bool(getattr(self, product.value))


class JurisdictionProfile(_Strict):
    name: str
    description: str = ""
    max_leverage: Decimal = Decimal("1.0")
    venues: dict[str, VenuePermission] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def permission(self, venue: str) -> VenuePermission:
        return self.venues.get(venue, VenuePermission())

    def can_trade(self, venue: str, product: Product) -> bool:
        return self.permission(venue).allows(product)

    def can_read(self, venue: str) -> bool:
        perm = self.permission(venue)
        return perm.read or any(perm.allows(p) for p in Product)


class AccountLimits(_Strict):
    max_daily_loss_pct: Decimal = Decimal("3")
    max_drawdown_pct: Decimal = Decimal("20")
    max_gross_leverage: Decimal = Decimal("1.0")


class SleeveLimits(_Strict):
    max_drawdown_pct: Decimal = Decimal("25")
    max_capital_pct: Decimal = Decimal("100")


class OrderLimits(_Strict):
    max_order_notional_usd: Decimal = Decimal("50")
    max_position_notional_usd: Decimal = Decimal("100")
    price_band_pct: Decimal = Decimal("2")  # reject limits further than this from mid
    exit_depth_multiple: Decimal = Decimal("20")  # book depth must be >= this x order qty


class RiskConfig(_Strict):
    account: AccountLimits = AccountLimits()
    sleeve_defaults: SleeveLimits = SleeveLimits()
    sleeves: dict[str, SleeveLimits] = Field(default_factory=dict)
    orders: OrderLimits = OrderLimits()
    kelly_fraction_cap: Decimal = Decimal("0.5")
    edge_haircut: Decimal = Decimal("0.5")

    @model_validator(mode="after")
    def _sane(self) -> RiskConfig:
        if not Decimal("0") < self.kelly_fraction_cap <= Decimal("0.5"):
            raise ValueError("kelly_fraction_cap must be in (0, 0.5]; full Kelly is not allowed")
        if self.account.max_gross_leverage > Decimal("3"):
            raise ValueError("max_gross_leverage above 3x is outside the spec")
        return self

    def sleeve(self, name: str) -> SleeveLimits:
        return self.sleeves.get(name, self.sleeve_defaults)


class VenueConfig(_Strict):
    name: str
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    min_notional_usd: Decimal = Decimal("0")
    max_orders_per_second: Decimal = Decimal("5")
    testnet_available: bool = False
    notes: list[str] = Field(default_factory=list)


class JurisdictionSetting(_Strict):
    active: str


class Settings(_Strict):
    """Everything loaded from config/. Built once at startup."""

    mode: Mode = Mode.BACKTEST
    base_currency: str = "USD"
    jurisdiction: JurisdictionSetting
    jurisdictions: dict[str, JurisdictionProfile]
    risk: RiskConfig
    venues: dict[str, VenueConfig]

    @model_validator(mode="after")
    def _active_exists(self) -> Settings:
        if self.jurisdiction.active not in self.jurisdictions:
            raise ValueError(
                f"active jurisdiction '{self.jurisdiction.active}' has no profile in "
                f"config/jurisdictions/ (have: {sorted(self.jurisdictions)})"
            )
        return self

    @property
    def active_jurisdiction(self) -> JurisdictionProfile:
        return self.jurisdictions[self.jurisdiction.active]
