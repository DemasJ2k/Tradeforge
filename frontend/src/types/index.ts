export interface User {
  id: number;
  username: string;
  email: string;
  phone: string;
  is_admin: boolean;
  totp_enabled: boolean;
  must_change_password: boolean;
}

export interface Token {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
  totp_required: boolean;
}

export interface Invitation {
  id: number;
  email: string;
  username: string;
  status: string;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

export interface NavItem {
  name: string;
  href: string;
  icon: string;
}

export interface DataSource {
  id: number;
  filename: string;
  symbol: string;
  timeframe: string;
  data_type: string;
  row_count: number;
  date_from: string;
  date_to: string;
  columns: string;
  file_size_mb: number;
  source_type: string;
  broker_name: string;
}

export interface DataSourceList {
  items: DataSource[];
  total: number;
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface CandleResponse {
  symbol: string;
  timeframe: string;
  candles: CandleData[];
  total: number;
}

// --- Strategy Types ---

export interface IndicatorConfig {
  id: string;
  type: string;
  params: Record<string, number | string>;
  overlay: boolean;
}

export interface ConditionRow {
  left: string;
  operator: string;
  right: string;
  logic: string;
  direction: string;  // "long" | "short" | "both"
}

export interface RiskParams {
  position_size_type: string;
  position_size_value: number;
  stop_loss_type: string;
  stop_loss_value: number;
  take_profit_type: string;
  take_profit_value: number;
  take_profit_2_type: string;
  take_profit_2_value: number;
  lot_split: number[];
  breakeven_on_tp1: boolean;
  trailing_stop: boolean;
  trailing_stop_type: string;
  trailing_stop_value: number;
  max_positions: number;
  max_drawdown_pct: number;
}

export interface FilterConfig {
  time_start: string;
  time_end: string;
  days_of_week: number[];
  min_volatility: number;
  max_volatility: number;
  min_adx: number;
  max_adx: number;
}

export interface Strategy {
  id: number;
  name: string;
  description: string;
  indicators: IndicatorConfig[];
  entry_rules: ConditionRow[];
  exit_rules: ConditionRow[];
  risk_params: Partial<RiskParams>;
  filters: Partial<FilterConfig>;
  creator_id: number;
  is_system: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyList {
  items: Strategy[];
  total: number;
}

// --- Backtest Types ---

export interface BacktestRequest {
  strategy_id: number;
  datasource_id: number;
  initial_balance: number;
  spread_points: number;
  commission_per_lot: number;
  point_value: number;
}

export interface TradeResult {
  entry_bar: number;
  entry_time: number;
  entry_price: number;
  direction: string;
  size: number;
  stop_loss: number;
  take_profit: number;
  exit_bar: number | null;
  exit_time: number | null;
  exit_price: number | null;
  exit_reason: string;
  pnl: number;
  pnl_pct: number;
}

export interface BacktestStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  gross_profit: number;
  gross_loss: number;
  net_profit: number;
  profit_factor: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  avg_trade: number;
  sharpe_ratio: number;
  expectancy: number;
  total_bars: number;
}

export interface BacktestResponse {
  id: number;
  strategy_id: number;
  datasource_id: number;
  status: string;
  stats: BacktestStats;
  trades: TradeResult[];
  equity_curve: number[];
}

export interface BacktestListItem {
  id: number;
  strategy_id: number;
  symbol: string;
  timeframe: string;
  status: string;
  stats: Partial<BacktestStats>;
  created_at: string;
}

// --- Settings Types ---

export interface UserSettings {
  display_name: string;
  theme: string;
  accent_color: string;
  font_size: string;
  compact_mode: boolean;
  chart_up_color: string;
  chart_down_color: string;
  chart_volume_color: string;
  chart_grid: boolean;
  chart_crosshair: boolean;
  llm_provider: string;
  llm_api_key_set: boolean;
  llm_model: string;
  llm_temperature: string;
  llm_max_tokens: string;
  llm_system_prompt: string;
  default_balance: string;
  default_spread: string;
  default_commission: string;
  default_point_value: string;
  default_risk_pct: string;
  preferred_instruments: string;
  preferred_timeframes: string;
  default_broker: string;
  csv_retention_days: number;
  export_format: string;
  max_storage_mb: number;
  session_timeout_minutes: number;
  notifications: Record<string, boolean>;
}

export interface StorageInfo {
  total_csvs: number;
  total_size_mb: number;
  oldest_file: string;
  newest_file: string;
}

// --- Broker Credentials ---

export interface BrokerCredentialMasked {
  broker: string;
  configured: boolean;
  auto_connect: boolean;
  connected: boolean;
  fields_set: string[];
}

export interface BrokerCredentialsResponse {
  brokers: BrokerCredentialMasked[];
}

// --- LLM / Chat Types ---

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
}

export interface ChatRequest {
  message: string;
  conversation_id?: number | null;
  page_context?: string;
  context_data?: Record<string, unknown>;
}

export interface ChatResponse {
  reply: string;
  conversation_id: number;
  title: string;
  tokens_in: number;
  tokens_out: number;
  model: string;
}

export interface ConversationSummary {
  id: number;
  title: string;
  page_context: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  id: number;
  title: string;
  page_context: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}

export interface ConversationList {
  items: ConversationSummary[];
  total: number;
}

export interface MemoryItem {
  id: number;
  key: string;
  value: string;
  category: string;
  confidence: number;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface UsageStats {
  total_conversations: number;
  total_messages: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_estimate: number;
  provider_breakdown: Record<string, {
    tokens_in: number;
    tokens_out: number;
    cost: number;
    calls: number;
  }>;
}

// --- Optimization Types ---

export interface ParamRange {
  param_path: string;
  param_type: "int" | "float" | "categorical";
  min_val?: number;
  max_val?: number;
  step?: number;
  choices?: (string | number)[];
  label: string;
}

export interface OptimizationRequest {
  strategy_id: number;
  datasource_id: number;
  param_space: ParamRange[];
  objective: string;
  n_trials: number;
  method: string;
  initial_balance: number;
  spread_points: number;
  commission_per_lot: number;
  point_value: number;
  walk_forward: boolean;
  wf_in_sample_pct: number;
  secondary_objective?: string;
  secondary_threshold?: number;
  secondary_operator?: '>=' | '<=';
}

export interface TrialResult {
  trial_number: number;
  params: Record<string, number | string>;
  score: number;
  stats: Record<string, number>;
}

export interface OptimizationResponse {
  id: number;
  strategy_id: number;
  status: string;
  objective: string;
  n_trials: number;
  best_params: Record<string, number | string>;
  best_score: number;
  history: TrialResult[];
  param_importance: Record<string, number>;
}

export interface OptimizationStatus {
  id: number;
  status: string;
  progress: number;
  current_trial: number;
  total_trials: number;
  best_score: number;
  best_params: Record<string, number | string>;
  elapsed_seconds: number;
}

export interface OptimizationListItem {
  id: number;
  strategy_id: number;
  strategy_name: string;
  objective: string;
  n_trials: number;
  status: string;
  best_score: number;
  created_at: string;
}

// --- Broker / Live Trading Types ---

export interface BrokerConnectRequest {
  broker: string;
  api_key: string;
  account_id: string;
  practice: boolean;
  extra?: Record<string, unknown>;
}

export interface BrokerStatusInfo {
  connected: boolean;
  broker_name: string;
  is_default: boolean;
}

export interface BrokerListResponse {
  brokers: Record<string, BrokerStatusInfo>;
  default_broker: string | null;
}

export interface AccountInfo {
  account_id: string;
  broker: string;
  currency: string;
  balance: number;
  equity: number;
  unrealized_pnl: number;
  margin_used: number;
  margin_available: number;
  open_positions: number;
  open_orders: number;
}

export interface LivePosition {
  position_id: string;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  margin_used: number;
  open_time: string;
  stop_loss: number | null;
  take_profit: number | null;
}

export interface LiveOrder {
  order_id: string;
  symbol: string;
  side: string;
  order_type: string;
  size: number;
  price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: string;
  filled_price: number | null;
  filled_time: string | null;
  created_time: string | null;
}

export interface PlaceOrderRequest {
  symbol: string;
  side: string;
  size: number;
  order_type: string;
  price?: number;
  stop_loss?: number;
  take_profit?: number;
  trailing_stop_distance?: number;
  comment?: string;
  broker?: string;
}

export interface SymbolInfo {
  symbol: string;
  display_name: string;
  base_currency: string;
  quote_currency: string;
  pip_size: number;
  min_lot: number;
  max_lot: number;
  lot_step: number;
  margin_rate: number;
  tradeable: boolean;
  asset_class: string;
}

export interface PriceTick {
  symbol: string;
  bid: number;
  ask: number;
  spread: number;
  timestamp: string;
}

export interface TradeHistory {
  id: number;
  broker: string;
  symbol: string;
  direction: string;
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  lot_size: number;
  pnl: number | null;
  commission: number;
  status: string;
}

// --- Knowledge Base Types ---

export interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface KnowledgeArticle {
  id: number;
  title: string;
  content: string;
  category: string;
  difficulty: string;
  quiz_questions: QuizQuestion[];
  author_id: number | null;
  source_type: string;
  external_url: string;
  order_index: number;
  created_at: string;
  updated_at: string;
}

export interface ArticleListItem {
  id: number;
  title: string;
  category: string;
  difficulty: string;
  source_type: string;
  has_quiz: boolean;
  quiz_count: number;
  order_index: number;
  created_at: string;
}

export interface QuizResult {
  article_id: number;
  score: number;
  total_questions: number;
  percentage: number;
  details: {
    question: string;
    selected: number;
    correct: number;
    is_correct: boolean;
    explanation: string;
    options: string[];
  }[];
}

export interface QuizAttempt {
  id: number;
  article_id: number;
  article_title: string;
  score: number;
  total_questions: number;
  percentage: number;
  created_at: string;
}

export interface CategoryProgress {
  category: string;
  total_articles: number;
  articles_read: number;
  quizzes_taken: number;
  avg_quiz_score: number;
}

export interface KnowledgeProgress {
  total_articles: number;
  total_quizzes_taken: number;
  avg_quiz_score: number;
  categories: CategoryProgress[];
  recent_attempts: QuizAttempt[];
}

export interface CategoryInfo {
  categories: string[];
  counts: Record<string, number>;
  labels: Record<string, string>;
}

// --- ML Lab Types ---

export interface MLModelListItem {
  id: number;
  name: string;
  level: number;
  model_type: string;
  symbol: string;
  timeframe: string;
  status: string;
  train_accuracy: number | null;
  val_accuracy: number | null;
  n_features: number;
  created_at: string;
}

export interface MLModelDetail {
  id: number;
  name: string;
  level: number;
  model_type: string;
  symbol: string;
  timeframe: string;
  status: string;
  features_config: Record<string, unknown>;
  target_config: Record<string, unknown>;
  hyperparams: Record<string, unknown>;
  train_metrics: Record<string, number>;
  val_metrics: Record<string, number>;
  feature_importance: Record<string, number>;
  created_at: string;
  trained_at: string | null;
  error_message: string;
}

export interface MLPredictionResult {
  model_id: number;
  model_name: string;
  predictions: {
    bar_index: number;
    prediction: number;
    confidence: number;
    features: Record<string, number>;
  }[];
  total_predictions: number;
  avg_confidence: number;
}

export interface FeatureList {
  available_features: string[];
  descriptions: Record<string, string>;
}

// --- ML Action Plan (LLM-driven training) ---

export interface MLActionPlan {
  action: string;
  name: string;
  level: number;
  model_type: string;
  datasource_id: number;
  datasource_name: string;
  datasource_info: string;
  symbol: string;
  timeframe: string;
  target_type: string;
  target_horizon: number;
  features: string[];
  n_estimators: number;
  max_depth: number;
  learning_rate: number;
  explanation: string;
  tokens_used: { input: number; output: number };
}

// --- Algo Trading Agent Types ---

export type AgentMode = "paper" | "confirmation" | "auto";
export type AgentStatus = "stopped" | "running" | "paused" | "error";
export type AgentTradeStatus = "pending_confirmation" | "confirmed" | "executed" | "rejected" | "paper" | "closed";

export interface AgentRiskConfig {
  max_daily_loss?: number;
  max_daily_loss_pct?: number;
  max_open_positions?: number;
  max_drawdown_pct?: number;
  position_size_type?: string;
  position_size_value?: number;
  max_exposure_per_symbol?: number;
}

export interface Agent {
  id: number;
  name: string;
  strategy_id: number;
  broker_name: string;
  symbol: string;
  timeframe: string;
  mode: AgentMode;
  status: AgentStatus;
  risk_config: AgentRiskConfig;
  performance_stats: Record<string, number>;
  ml_model_id?: number | null;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface AgentList {
  items: Agent[];
  total: number;
}

export interface AgentCreateRequest {
  name: string;
  strategy_id: number;
  symbol: string;
  timeframe?: string;
  broker_name?: string;
  mode?: AgentMode;
  risk_config?: AgentRiskConfig;
  ml_model_id?: number | null;
}

export interface AgentUpdateRequest {
  name?: string;
  mode?: AgentMode;
  risk_config?: AgentRiskConfig;
  ml_model_id?: number | null;
}

export interface AgentLog {
  id: number;
  agent_id: number;
  level: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface AgentLogList {
  items: AgentLog[];
  total: number;
}

export interface AgentTrade {
  id: number;
  agent_id: number;
  symbol: string;
  direction: string;
  entry_price: number | null;
  exit_price: number | null;
  lot_size: number;
  stop_loss: number | null;
  take_profit_1: number | null;
  take_profit_2: number | null;
  pnl: number;
  pnl_pct: number;
  status: AgentTradeStatus;
  signal_type: string | null;
  signal_reason: string | null;
  signal_confidence: number;
  broker_ticket: string | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
}

export interface AgentTradeList {
  items: AgentTrade[];
  total: number;
}

export interface AgentPerformance {
  agent_id: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  equity_curve: { time: string; pnl: number }[];
}

// --- Market Data Types ---

export interface MarketCandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketCandleResponse {
  symbol: string;
  timeframe: string;
  provider: string;
  candles: MarketCandleData[];
  total: number;
}

export interface ProviderStatus {
  name: string;
  available: boolean;
  provider_type: string;
}

export interface ProviderListResponse {
  providers: ProviderStatus[];
}
