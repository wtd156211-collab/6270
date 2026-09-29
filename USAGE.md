# 使用与复现说明

## 公开接口（`heavyhitters.py`，库即入口）

- `HeavyHitters(num, den)`：Misra-Gries 摘要。`offer(key: bytes)` 喂一个键；
  `n` 已读条数；`error_bound` 当前误差界 D；`bound_limit()` 误差界上限 B；
  `hits()` 返回 `(键, 估计频次, 误差界)`，按估计降序、并列按键 ASCII 升序。
- `run(stream_name, result_name, num, den) -> int`：单遍扫描并写结果文件。
- `report(result_name, page_name) -> int`：只读结果文件，渲染自包含页面。
- `main(argv)`：命令行入口。返回 0 跑完；1 输入不可用且不写输出文件。

```
python heavyhitters.py run <流文件> <结果文件> --eps <分子>/<分母>
python heavyhitters.py report <结果文件> <页面文件>
```

## 复现命令（仓库根目录）

```sh
# 对拍：逐样例跑 run，与 samples/expected/<同名>.txt 按 README 第五节口径核对
python heavyhitters.py run samples/streams/05-scale-1e7.txt /tmp/05.out --eps 1/10000
python heavyhitters.py report /tmp/05.out heavyhitters.html

# 测试（含对拍、不变量、确定性、内存、页面、CLI 退出码）
python -m unittest discover -s tests

# 内存复现（tracemalloc 扣基线，上限 24 MiB）
python - << 'EOF'
import tracemalloc, heavyhitters
tracemalloc.start()
base, _ = tracemalloc.get_traced_memory()
heavyhitters.run("samples/streams/05-scale-1e7.txt", "/tmp/05.out", 1, 10000)
_, peak = tracemalloc.get_traced_memory()
print("peak-baseline MiB:", (peak - base) / 2**20)
EOF
```

本机实测：05 号 `run` 约 1 秒（上限 30 秒），峰值分配约 0.2 MiB（上限 24 MiB）；
04 号约 0.1 秒、0.2 MiB；`report` 毫秒级。

## 结构参数取值理由

选 Misra-Gries 摘要：最多 `m = ⌊分母/分子⌋` 条记录，新键到来且结构已满时
全体计数减一、删归零记录，记一轮扣减，全局扣减轮数 D 即每条记录的误差界。

- **零漏检**：不变量 `est ≤ f ≤ est + D`（结构外键 `f ≤ D`）。必须报的键
  满足 `f×分母 > N×分子`，若它不在结构里则 `f ≤ D ≤ ⌊N/(m+1)⌋ ≤ ⌊分子×N/分母⌋`，
  矛盾，故必在结构中；且 `估计+误差界 = est + D ≥ f > θ`，必被报出。
- **误差界**：每轮扣减摊掉 `m+1` 条出现，`D ≤ ⌊N/(m+1)⌋`。取 `m+1 > 分母/分子`
  （即 `m = ⌊分母/分子⌋`）得 `D ≤ ⌊分子×N/分母⌋ = B`，且严格 `D < θ`，
  所以只出现一次的键 `est + D ≤ 1 + D ≤ θ` 永不误报，命中行数被
  「频次 ≥ 2 的键数」自然压住，各样例均低于命中上限。
- **报告规模**：命中数 ≤ m，只随 eps 增长，与不同键数无关（04 号 59 万不同键
  也只占 m = 1000 条记录）。
- **内存**：m 条 `(bytes 键, int 计数)`，eps = 1/10000 时 m = 10000，
  实测峰值约 0.2 MiB，对 24 MiB 上限余量两个数量级；更大规模只涨流长不涨结构。
- **确定性**：阈值比较全程整数 `(est + D)×分母 > 分子×N`，无浮点、无随机、
  输出前显式排序，两遍运行逐字节相同。

## 页面口径

`report` 只读结果文件、不重算频次。页面摘要标注：结果文件名、流文件名、
总条数 N、eps、误差界上限 B、阈值 θ（不约分的 `分子×N/分母`）、命中数、
其中精确数；排行按结果文件顺序给名次/键/估计频次/误差界，`exact`（绿）/
`est`（橙）配色并附图例；每条命中横条长度按估计频次，误差界以红色段单独
标出。`<script id="hits" type="text/plain">` 内嵌结果文件（去末尾换行）
逐字节相同，全部数值取自该内嵌结果。
