"use client";

import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

interface HelperButton {
  icon: string;
  label: string;
  prompt: string;
  color?: "accent" | "success" | "danger" | "info";
}

/**
 * Get context-specific helper buttons based on current page
 */
function getHelperButtons(pathname: string): HelperButton[] {
  // Strategies page helpers
  if (pathname.includes("/strategies")) {
    return [
      {
        icon: "💡",
        label: "Suggest entry/exit rules",
        prompt: "Based on my trading experience, suggest entry and exit rules that typically work well with trending markets. Consider using RSI and MACD indicators.",
        color: "accent",
      },
      {
        icon: "📊",
        label: "Explain indicator combination",
        prompt: "Explain how to combine multiple indicators (like RSI, MACD, and Bollinger Bands) effectively to avoid false signals.",
        color: "info",
      },
      {
        icon: "🚀",
        label: "Generate from description",
        prompt: "I want a scalping strategy for 5-minute charts with quick entries and exits. Can you help me define the rules?",
        color: "accent",
      },
      {
        icon: "⚠️",
        label: "Review for risks",
        prompt: "I have a strategy with multiple indicators. Please identify potential weaknesses, over-optimization issues, and risk management gaps.",
        color: "danger",
      },
    ];
  }

  // Backtest Results page helpers
  if (pathname.includes("/backtest")) {
    return [
      {
        icon: "📈",
        label: "Explain these results",
        prompt: "I just ran a backtest. Can you help me understand the key metrics like Sharpe ratio, profit factor, and max drawdown?",
        color: "info",
      },
      {
        icon: "📉",
        label: "Why underperformed?",
        prompt: "My strategy showed poor results in the last backtest. What could be the reasons (market conditions, indicator lag, slippage)?",
        color: "danger",
      },
      {
        icon: "✨",
        label: "Suggest improvements",
        prompt: "Based on typical backtest analysis, how can I improve win rate, reduce drawdown, and increase profit factor?",
        color: "success",
      },
      {
        icon: "🎯",
        label: "Analyze equity curve",
        prompt: "Can you explain what a good vs bad equity curve looks like and how to spot periods of overheating or drawdown?",
        color: "info",
      },
    ];
  }

  // Optimization page helpers
  if (pathname.includes("/optimize") || pathname.includes("/ml")) {
    return [
      {
        icon: "🔍",
        label: "Suggest parameter ranges",
        prompt: "What are typical parameter ranges for common indicators like RSI (oversold/overbought levels), Moving Averages (periods), and Bollinger Bands (standard deviations)?",
        color: "accent",
      },
      {
        icon: "⚙️",
        label: "Explain parameter importance",
        prompt: "How sensitive is a trading strategy to parameter changes? Which parameters typically have the most impact on performance?",
        color: "info",
      },
      {
        icon: "⚡",
        label: "Detect overfitting",
        prompt: "I optimized my strategy parameters on historical data. How can I tell if it's overfitted? What are the red flags?",
        color: "danger",
      },
      {
        icon: "🧪",
        label: "Walk-forward testing",
        prompt: "Explain walk-forward analysis and why it's better than traditional backtesting for avoiding overfitting.",
        color: "success",
      },
    ];
  }

  // Chart page helpers
  if (pathname.includes("/chart")) {
    return [
      {
        icon: "🔎",
        label: "Identify patterns",
        prompt: "What chart patterns should I look for in candlestick charts? (e.g., head and shoulders, double tops, triangles)",
        color: "accent",
      },
      {
        icon: "📍",
        label: "Support & resistance",
        prompt: "Help me understand how to identify and draw support and resistance levels on a price chart. Why do these levels matter?",
        color: "info",
      },
      {
        icon: "📊",
        label: "Technical analysis basics",
        prompt: "Explain the fundamentals of technical analysis and how different chart timeframes affect trading decisions.",
        color: "info",
      },
      {
        icon: "🎯",
        label: "Entry/exit signals",
        prompt: "Based on the chart, what visual patterns and signals typically indicate good entry and exit points?",
        color: "accent",
      },
    ];
  }

  // Knowledge base page helpers
  if (pathname.includes("/knowledge")) {
    return [
      {
        icon: "📝",
        label: "Generate article",
        prompt: "Write an educational article about momentum trading strategies, including entry methods, risk management, and real-world examples.",
        color: "accent",
      },
      {
        icon: "📚",
        label: "Create study guide",
        prompt: "Create a study guide covering fundamental concepts: volatility, correlation, sharpe ratio, and their impact on portfolio design.",
        color: "success",
      },
      {
        icon: "❓",
        label: "Create quiz",
        prompt: "Create a quiz with 5 questions about technical indicators (RSI, MACD, Bollinger Bands) with explanations for each answer.",
        color: "info",
      },
      {
        icon: "💬",
        label: "Q&A mode",
        prompt: "I have questions about risk management in trading. Can you answer whatever questions I ask about position sizing, stop losses, and portfolio allocation?",
        color: "accent",
      },
    ];
  }

  // Data page helpers
  if (pathname.includes("/data")) {
    return [
      {
        icon: "📊",
        label: "Data quality tips",
        prompt: "What should I check when uploading CSV data to ensure quality? (missing values, outliers, data alignment)",
        color: "info",
      },
      {
        icon: "📈",
        label: "Data requirements",
        prompt: "What kind of data do I need (timeframe, columns, date format) for backtesting and technical analysis?",
        color: "accent",
      },
      {
        icon: "🧹",
        label: "Clean dataset",
        prompt: "How should I handle missing data, gaps, and outliers in my trading dataset?",
        color: "info",
      },
    ];
  }

  // Trading page (live trading) helpers
  if (pathname.includes("/trading")) {
    return [
      {
        icon: "🚨",
        label: "Risk management",
        prompt: "Explain position sizing, risk per trade, account management, and how to calculate appropriate stop losses.",
        color: "danger",
      },
      {
        icon: "🎯",
        label: "Trading psychology",
        prompt: "What are common emotional trading mistakes and how can I maintain discipline in live trading?",
        color: "info",
      },
      {
        icon: "💰",
        label: "Money management",
        prompt: "How should I allocate my trading account across different strategies, instruments, and timeframes?",
        color: "accent",
      },
    ];
  }

  // Settings page helpers
  if (pathname.includes("/settings")) {
    return [
      {
        icon: "🤖",
        label: "Configure AI assistant",
        prompt: "I want to set up the AI assistant. What API key should I use (Claude, OpenAI, or Gemini)? What's the difference?",
        color: "info",
      },
      {
        icon: "⚙️",
        label: "Optimize settings",
        prompt: "What are recommended settings for the LLM (temperature, token limit) for technical trading analysis?",
        color: "accent",
      },
    ];
  }

  // Default helpers for dashboard/unknown pages
  return [
    {
      icon: "📖",
      label: "Ask me anything",
      prompt: "Tell me about your trading experience, and I'll provide personalized advice on strategies, risk management, and technical analysis.",
      color: "accent",
    },
    {
      icon: "📚",
      label: "Learning resources",
      prompt: "What are good resources to learn about trading? Can you recommend books, courses, or key concepts to master?",
      color: "info",
    },
    {
      icon: "🎓",
      label: "Educational Q&A",
      prompt: "I'm new to trading. Can you explain fundamental concepts like trends, support/resistance, and risk management?",
      color: "success",
    },
  ];
}

/**
 * ChatHelpers Component
 * Renders contextual helper buttons below a page's main content
 * Buttons pre-fill the chat sidebar with relevant prompts via __chatPrefill global function
 */
export default function ChatHelpers() {
  const pathname = usePathname();
  const [showAllKey, setShowAllKey] = useState("");
  const showAll = showAllKey === pathname;
  const setShowAll = (val: boolean) => setShowAllKey(val ? pathname : "");
  const buttons = useMemo(() => getHelperButtons(pathname), [pathname]);

  if (buttons.length === 0) return null;

  const displayedButtons = showAll ? buttons : buttons.slice(0, 2);

  const handleClick = (prompt: string) => {
    // Access the global __chatPrefill function exposed by ChatSidebar
    const prefill = (window as unknown as Record<string, unknown>).__chatPrefill as ((text: string) => void) | undefined;
    if (typeof prefill === "function") {
      prefill(prompt);
    }
  };

  const colorClasses = {
    accent: "bg-accent/10 border-accent/30 text-accent hover:bg-accent/20 hover:border-accent/50",
    success: "bg-success/10 border-success/30 text-success hover:bg-success/20 hover:border-success/50",
    danger: "bg-danger/10 border-danger/30 text-danger hover:bg-danger/20 hover:border-danger/50",
    info: "bg-blue-500/10 border-blue-500/30 text-blue-400 hover:bg-blue-500/20 hover:border-blue-500/50",
  };

  return (
    <div className="mt-8 space-y-3">
      <div className="flex items-center gap-2">
        <svg className="h-4 w-4 text-muted" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5h.01" />
        </svg>
        <span className="text-xs font-medium text-muted">AI Assistant Suggestions</span>
      </div>

      <div className="grid gap-2">
        {displayedButtons.map((btn, i) => (
          <button
            key={i}
            onClick={() => handleClick(btn.prompt)}
            className={`flex items-start gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-all ${
              colorClasses[btn.color || "accent"]
            }`}
          >
            <span className="mt-0.5 text-lg">{btn.icon}</span>
            <span className="flex-1 font-medium">{btn.label}</span>
            <svg className="h-4 w-4 shrink-0 opacity-40" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
            </svg>
          </button>
        ))}
      </div>

      {buttons.length > 2 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-muted hover:text-foreground transition-colors px-3 py-1"
        >
          {showAll ? `← Show less` : `+ Show ${buttons.length - 2} more suggestions`}
        </button>
      )}
    </div>
  );
}
