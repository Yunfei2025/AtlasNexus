from web.tabs.alpha.data.loaders import load_spread_data

df = load_spread_data('CBondCurve')
print(type(df))
print(df.head().to_string())
print('index contains 250208.IB', '250208.IB' in df.index)
if '250208.IB' in df.index:
    print(df.loc['250208.IB'])
