"""veval 配套工具集：数据集自检 / 合成数据 / 标注草稿与校正。

模块一览：
  inspect  数据集统计（图片数、标注覆盖、box 覆盖、缺标注 ID）
  synth    PIL 渲染合成中文数据集，自动产出带真实像素 box 的 L2 标注
  label    引擎草稿 GT（draft）+ 自包含 HTML 校正页（review）
"""
