import pandas as pd
df = pd.read_csv(r'D:\Doc\DATA\Backtest Data\BTCUSD_M5.csv')
print(f"Total rows: {len(df):,}")
print(f"Date range: {df.iloc[0, 0]} to {df.iloc[-1, 0]}")
print(f"Columns: {df.columns.tolist()}")
print(f"Price range: ${df['low'].min():.2f} to ${df['high'].max():.2f}")
print(f"Volume stats: mean={df['volume'].mean():.2f}, median={df['volume'].median():.2f}")
