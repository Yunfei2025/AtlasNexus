from web.tabs.alpha.layouts import build_individual_backtest_panel


def _collect_style_values(node, out=None):
    if out is None:
        out = []

    if isinstance(node, dict):
        if 'gridTemplateColumns' in node:
            out.append(node['gridTemplateColumns'])
        for value in node.values():
            _collect_style_values(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_style_values(item, out)
    elif hasattr(node, 'children'):
        if node.children is not None:
            _collect_style_values(node.children, out)
    return out


def test_individual_backtest_layout_is_not_locked_to_76px_columns():
    panel = build_individual_backtest_panel()
    style_values = _collect_style_values(panel)

    assert not any('76px' in value for value in style_values)
    assert any('minmax' in value for value in style_values)


if __name__ == '__main__':
    test_individual_backtest_layout_is_not_locked_to_76px_columns()
    print('alpha layout regression ok')
