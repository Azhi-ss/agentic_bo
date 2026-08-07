# 电池正极材料合成优化评测集 — battery_cathode

## 数据集信息

| 属性 | 值 |
| --- | --- |
| 领域 | 锂离子电池正极材料 (LiFePO4 Cathode Synthesis) |
| 数据来源 | Text-to-BatteryRecipe (KIST-CSRC), 论文原文 NLP 抽取 |
| 优化目标 | 最大化 `Discharge_Capacity_mAh_g` (mAh/g) |
| 优化变量数量 | 4 (`Precursor`, `Sintering_Time_Hours`, `Atmosphere`, `Solvent`) |
| 搜索空间样本数 | 549 |
| 默认训练集样本数 | 10 |
| 测试样本数 | 539 |

## 数据走势与物理特征 (关键信息)

基于统计分析，该数据集呈现出典型的材料科学“长尾分布”特征，极其适合用于基于物理先验与大语言模型 (LLM) 增强的贝叶斯优化测试：
- **容量分布**: 平均容量为 162.1 mAh/g，中位数为 170.0 mAh/g。绝大多数样本 (66%) 集中在 160 - 180 mAh/g，仅有极少数 (约 4%) 突破了 180 mAh/g，达到了全局最优的 200.0 mAh/g。
- **气氛 (Atmosphere)**: 虽然理论上 LFP 需要惰性或还原气氛（如 Ar, N2, H2）以防氧化，但数据中空气气氛 (Air) 也存在容量高达 200.0 mAh/g 的异常值（推测因前驱体含强碳源导致碳热还原）。
- **时间 (Sintering_Time)**: 并非越长越好，超长时间（>24h）因晶粒粗化等原因导致平均容量大幅下降。常规极值主要出现在 1~12 小时内。

## 特征与目标说明

| 列名 | 说明 |
| --- | --- |
| `Precursor` | 正极合成前驱体 (经过字符串清理，如 `LiH2PO4`, `Li2CO3`, `FePO4` 等，共计 251 种组合) |
| `Sintering_Time_Hours` | 烧结保温时间，已统一转化为浮点数小时制 (如 10.0, 2.0) |
| `Atmosphere` | 烧结气氛 (统一清洗归类为 `Ar`, `N2`, `Reducing (H2)`, `Air`, `Vacuum`, `Ar/N2`, `Other`) |
| `Solvent` | 合成溶剂 (去除了异常数值项，如 `deionized water`, `ethanol`, `NMP`) |
| `Discharge_Capacity_mAh_g` | 目标: 放电比容量 (mAh/g), 取值范围为 60.0 ~ 200.0 |

## 数据清洗说明 (2026 更新版)

在原始数据的提取基础之上，对数据进行了深度标准化清洗：
1. **时间单位转换**: 将所有的 `Sintering_Time` 统一清洗并转化为浮点型 `Sintering_Time_Hours` (去除 'h' 等字符)。
2. **离散类别对齐**: 
   - 提取并分类合并了 `Atmosphere`，将类似 'argon', 'ar' 的全部映射到 `Ar`；把 'n2/h2', 'ar/h2' 等还原性气氛统一映射为 `Reducing (H2)`。
   - 去除了 `Solvent` 中的纯数字噪音行。
   - 对 `Precursor` 进行了纯文本格式的去冗余清理（如去除不需要的方括号和多余空格）。
3. **数据重组**: 生成了标准统一的 `options.json` 用于离散候选空间定义，并重新划分 `train/test` 集合。

## 文件结构

按照 BOagent 标准规范，文件布局如下：
- `searchspace.csv`: 完整 549 条候选搜索空间（包含目标变量）。
- `train.csv`: 默认 10 条带标签初始化训练集（冷启动数据）。
- `test.csv`: 测试集带标签数据（作为 Oracle 反馈）。
- `test_features.csv`: 测试集不含目标变量的特征池（提供给智能体进行推荐探索，防止数据泄露）。
- `options.json`: 各离散特征列的候选值字典映射。

## 数据来源文献

Text-to-Battery Recipe: A language modeling-based protocol for automatic battery recipe extraction and retrieval (KIST-CSRC)
https://github.com/KIST-CSRC/Text-to-BatteryRecipe
