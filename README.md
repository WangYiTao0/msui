# msui

小程序共享 UI 运行时与样式（pywebview + WebView2）：检测引导、参数化启动、调用桥骨架、tokens/base 样式与闸门。

设计与切票见 spec：[WangYiTao0/MSToolbox#107](https://github.com/WangYiTao0/MSToolbox/issues/107)。

## 安装（下游）

在 requirements 里写一行钉版本的 wheel URL，无需任何凭据：

```
msui @ https://github.com/WangYiTao0/msui/releases/download/v0.1.0/msui-0.1.0-py3-none-any.whl
```

## 发布（维护者）

版本号只写在 `pyproject.toml` 一处。发布：

```
git tag v<版本号> && git push origin v<版本号>
```

CI 在装依赖之前核对 tag 与 pyproject 版本一致（不一致当场 fail），跑测试，构建 wheel，用自带 GITHUB_TOKEN 发到本仓 Release——零 PAT。
