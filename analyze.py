import pandas as pd

#анализ пользователей

df = pd.read_csv('function_logs.csv')
print(df.groupby(['Function Type', 'Username']).size())