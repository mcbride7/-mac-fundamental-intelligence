"""Import every model so Base.metadata knows all tables."""
from app.models.analysis import (  # noqa: F401
    CurrencyScore,
    FundamentalAnalysis,
    MacroRegime,
    Scenario,
    ScenarioProbability,
    ScenarioTrigger,
    TradeBias,
    TradeSetup,
)
from app.models.central_bank import (  # noqa: F401
    CentralBankMeeting,
    CentralBankProjection,
    CentralBankSpeech,
    CentralBankStatement,
    CentralBankStatementVersion,
    PolicyDivergence,
    PolicyScore,
    ProjectionVintage,
)
from app.models.core import (  # noqa: F401
    CentralBank,
    EconomicEvent,
    EconomicForecast,
    EconomicRelease,
    Indicator,
    IndicatorObservation,
    Source,
    SourceDocument,
    SourceHealth,
)
from app.models.forecast import (  # noqa: F401
    ForecastAccuracy,
    ForecastBias,
    ForecastError,
    ForecastRevision,
)
from app.models.manual import (  # noqa: F401
    DataConfirmation,
    DataReconciliation,
    ExtractedDataPoint,
    ExtractionReview,
    ManualSubmission,
    ManualSubmissionFile,
    VerificationAttempt,
)
from app.models.market import (  # noqa: F401
    BondYield,
    EconomicSurprise,
    MarketPrice,
    MarketReaction,
    RateExpectation,
    YieldCurve,
)
from app.models.system import (  # noqa: F401
    Alert,
    AnalysisDependency,
    AuditLog,
    RecomputeJob,
    User,
    UserTrustSettings,
    Watchlist,
)
from app.models.track import SignalRecord  # noqa: F401,E402
from app.models.notify import AlertDelivery, Heartbeat  # noqa: F401,E402
from app.models.overrides import EventOverride  # noqa: F401,E402
from app.models.risk import RiskSentiment  # noqa: F401,E402
