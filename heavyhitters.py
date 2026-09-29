"""流式重击者检测引擎（Misra-Gries 摘要，单遍扫描）。

公开接口
--------
- ``HeavyHitters(num, den)``：摘要结构。``offer(key: bytes)`` 喂入一个键；
  ``n`` 已读条数；``error_bound`` 当前误差界（全局扣减轮数 D，只增不减）；
  ``bound_limit()`` 误差界上限 B = ⌊num*n/den⌋；``hits()`` 返回排好序的
  ``(key, 估计频次, 误差界)`` 列表（估计降序、并列按键 ASCII 升序）。
- ``run(stream_name, result_name, num, den) -> int``：单遍扫描流文件并写出
  结果文件；返回 0 成功，1 输入不可用（此时不写输出文件）。
- ``report(result_name, page_name) -> int``：只读结果文件，渲染自包含 HTML
  页面；返回 0 成功，1 输入不可用。
- ``main(argv=None) -> int``：命令行入口::

      python heavyhitters.py run <流文件> <结果文件> --eps <分子>/<分母>
      python heavyhitters.py report <结果文件> <页面文件>

结构与不变量
------------
Misra-Gries：最多 m = ⌊den/num⌋ 条记录（只随 eps 与常数增长，与不同键数
无关）。新键到来且结构已满时，全体计数减一并删除归零记录（新键不入结构），
记一轮扣减。不变量：任意时刻，对结构内记录 (key, est)，该键此刻真实频次 f
满足 est <= f <= est + D（D 为扣减轮数）；不在结构里的键 f <= D。
因此误差界取 D：D*(m+1) <= n 推出 D <= ⌊num*n/den⌋ = B，且 D < θ
（θ = num*n/den），故必须报的键（f*den > n*num）必然还在结构里且
est + D >= f > θ，零漏检；只出现一次的键 est + D <= 1 + D <= θ，永不误报。
阈值比较全程用整数 (est + D)*den > num*n，不用浮点。
"""

from __future__ import annotations

import argparse
import html
import sys


class HeavyHitters:
    """Misra-Gries 单遍重击者摘要。"""

    def __init__(self, num: int, den: int) -> None:
        if not (isinstance(num, int) and isinstance(den, int) and 0 < num < den):
            raise ValueError("eps 需满足 0 < 分子 < 分母")
        self.num = num
        self.den = den
        self.capacity = den // num  # m；扣减组大小 m+1 > den/num
        self._counts: dict[bytes, int] = {}
        self.decrements = 0  # D：全局扣减轮数，即每条记录的误差界
        self.n = 0

    def offer(self, key: bytes) -> None:
        counts = self._counts
        c = counts.get(key)
        if c is not None:
            counts[key] = c + 1
        elif len(counts) < self.capacity:
            counts[key] = 1
        else:
            self._counts = {k: v - 1 for k, v in counts.items() if v > 1}
            self.decrements += 1
        self.n += 1

    @property
    def error_bound(self) -> int:
        return self.decrements

    def bound_limit(self) -> int:
        return self.num * self.n // self.den

    def hits(self) -> list[tuple[bytes, int, int]]:
        d = self.decrements
        cut = self.num * self.n
        den = self.den
        selected = [(k, c) for k, c in self._counts.items() if (c + d) * den > cut]
        selected.sort(key=lambda kv: (-kv[1], kv[0]))
        return [(k, c, d) for k, c in selected]


def _parse_eps(text: str) -> tuple[int, int]:
    parts = text.split("/")
    if len(parts) != 2:
        raise ValueError(text)
    num, den = int(parts[0]), int(parts[1])
    if not 0 < num < den:
        raise ValueError(text)
    return num, den


def run(stream_name: str, result_name: str, num: int, den: int) -> int:
    hh = HeavyHitters(num, den)
    offer = hh.offer
    try:
        with open(stream_name, "rb") as fh:
            for line in fh:
                offer(line[:-1] if line.endswith(b"\n") else line)
    except OSError as exc:
        print(f"run: 无法读取流文件 {stream_name!r}: {exc}", file=sys.stderr)
        return 1
    n = hh.n
    d = hh.decrements
    hits = hh.hits()
    h = len(hits)
    exact = h if d == 0 else 0
    tag = "exact" if d == 0 else "est"
    est_sum = 0
    lines = [
        f"H|{stream_name}|N={n}|eps={num}/{den}|B={hh.bound_limit()}"
        f"|阈值={num * n}/{den}|命中={h}|精确={exact}"
    ]
    for key, c, b in hits:
        est_sum += c
        lines.append(f"E|{key.decode('utf-8')}|{c}|{b}|{tag}")
    lines.append(f"T|命中={h}|精确={exact}|估计合计={est_sum}|误差合计={d * h}")
    try:
        with open(result_name, "w", encoding="utf-8", newline="") as out:
            out.write("\n".join(lines) + "\n")
    except OSError as exc:
        print(f"run: 无法写入结果文件 {result_name!r}: {exc}", file=sys.stderr)
        return 1
    return 0


def _parse_result(text: str) -> tuple[dict[str, str], list[tuple[str, int, int, str]]]:
    lines = text.split("\n")
    if not lines or not lines[0].startswith("H|"):
        raise ValueError("缺少 H 行")
    header: dict[str, str] = {}
    parts = lines[0].split("|")
    if len(parts) != 8:
        raise ValueError("H 行字段数不对")
    header["流文件"] = parts[1]
    for field in parts[2:]:
        k, sep, v = field.partition("=")
        if not sep:
            raise ValueError("H 行字段缺少 =")
        header[k] = v
    for required in ("N", "eps", "B", "阈值", "命中", "精确"):
        if required not in header:
            raise ValueError(f"H 行缺少 {required}")
    entries: list[tuple[str, int, int, str]] = []
    for line in lines[1:-1]:
        eparts = line.split("|")
        if len(eparts) != 5 or eparts[0] != "E" or eparts[4] not in ("exact", "est"):
            raise ValueError(f"E 行格式错误: {line!r}")
        entries.append((eparts[1], int(eparts[2]), int(eparts[3]), eparts[4]))
    tparts = lines[-1].split("|")
    if len(tparts) != 5 or tparts[0] != "T":
        raise ValueError("缺少 T 行")
    if int(header["命中"]) != len(entries):
        raise ValueError("H 行命中数与 E 行数不一致")
    return header, entries


_PAGE_STYLE = """
body { font-family: "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 2em auto; max-width: 960px; color: #222; }
h1 { font-size: 1.4em; } h2 { font-size: 1.1em; margin-top: 1.6em; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4px 10px; text-align: left; font-size: 0.92em; }
th { background: #f2f2f2; }
.summary td:first-child { background: #f2f2f2; font-weight: bold; width: 12em; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 3px; color: #fff; font-size: 0.85em; }
.exact { background: #2e7d32; }
.est { background: #ef6c00; }
.legend span { margin-right: 1.5em; }
.bar-row { display: flex; align-items: center; margin: 3px 0; font-size: 0.9em; }
.bar-key { width: 14em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
           font-family: monospace; }
.bar { flex: 1; height: 16px; background: #eee; display: flex; }
.bar .fill-exact { background: #2e7d32; }
.bar .fill-est { background: #ef6c00; }
.bar .fill-err { background: #b71c1c; }
.bar-num { width: 16em; text-align: right; font-family: monospace; }
.footer { color: #777; font-size: 0.85em; margin-top: 2em; }
"""


def _render_page(result_name: str, header: dict[str, str],
                 entries: list[tuple[str, int, int, str]], content: str) -> str:
    esc = html.escape
    out = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>重击者检测报告 - {esc(result_name)}</title>",
        f"<style>{_PAGE_STYLE}</style>",
        "</head>",
        "<body>",
        "<h1>流式重击者检测报告</h1>",
        '<h2 id="summary-h">① 摘要</h2>',
        '<table class="summary">',
        f"<tr><td>结果文件</td><td>{esc(result_name)}</td></tr>",
        f"<tr><td>流文件</td><td>{esc(header['流文件'])}</td></tr>",
        f"<tr><td>总条数 N</td><td>{esc(header['N'])}</td></tr>",
        f"<tr><td>eps</td><td>{esc(header['eps'])}</td></tr>",
        f"<tr><td>误差界上限 B</td><td>{esc(header['B'])}</td></tr>",
        f"<tr><td>阈值 θ</td><td>{esc(header['阈值'])}</td></tr>",
        f"<tr><td>命中数</td><td>{esc(header['命中'])}</td></tr>",
        f"<tr><td>其中精确数</td><td>{esc(header['精确'])}</td></tr>",
        "</table>",
        '<p class="legend">图例：'
        '<span class="tag exact">exact</span>误差界为 0，估计值即精确值；'
        '<span class="tag est">est</span>估计值，与真实频次的偏差不超过所示误差界。'
        "横条中绿色/橙色段长度按估计频次，红色段为误差界。</p>",
        '<h2 id="ranking-h">② 排行</h2>',
        "<table>",
        "<tr><th>名次</th><th>键</th><th>估计频次</th><th>误差界</th><th>类型</th></tr>",
    ]
    if entries:
        for rank, (key, est, bound, tag) in enumerate(entries, 1):
            out.append(
                f'<tr><td>{rank}</td><td>{esc(key)}</td><td>{est}</td><td>{bound}</td>'
                f'<td><span class="tag {tag}">{tag}</span></td></tr>'
            )
    else:
        out.append('<tr><td colspan="5">无命中</td></tr>')
    out += ["</table>", '<h2 id="bars-h">③ 命中横条</h2>']
    if entries:
        max_est = entries[0][1]
        for key, est, bound, tag in entries:
            pct_est = 100.0 * est / max_est
            pct_err = 100.0 * bound / max_est
            out.append(
                '<div class="bar-row">'
                f'<span class="bar-key">{esc(key)}</span>'
                '<span class="bar">'
                f'<span class="fill-{tag}" style="width:{pct_est:.4f}%"></span>'
                f'<span class="fill-err" style="width:{pct_err:.4f}%"></span>'
                "</span>"
                f'<span class="bar-num">{est} ±{bound} {tag}</span>'
                "</div>"
            )
    out += [
        f'<p class="footer">本页面由 heavyhitters.py report 生成，全部数值取自内嵌结果文件 '
        f"{esc(result_name)}，未重算频次。</p>",
        f'<script id="hits" type="text/plain">{content}</script>',
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def report(result_name: str, page_name: str) -> int:
    try:
        with open(result_name, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        print(f"report: 无法读取结果文件 {result_name!r}: {exc}", file=sys.stderr)
        return 1
    try:
        text = raw.decode("utf-8")
        content = text[:-1] if text.endswith("\n") else text
        header, entries = _parse_result(content)
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"report: 结果文件格式错误 {result_name!r}: {exc}", file=sys.stderr)
        return 1
    page = _render_page(result_name, header, entries, content)
    try:
        with open(page_name, "w", encoding="utf-8", newline="") as out:
            out.write(page)
    except OSError as exc:
        print(f"report: 无法写入页面文件 {page_name!r}: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="heavyhitters.py", description="单遍流式重击者检测（Misra-Gries 摘要）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="扫描流文件并写出结果文件")
    p_run.add_argument("stream", help="流文件路径（一行一个键）")
    p_run.add_argument("result", help="结果文件输出路径")
    p_run.add_argument("--eps", required=True, help="相对误差，形如 <分子>/<分母>")
    p_rep = sub.add_parser("report", help="把结果文件渲染成自包含 HTML 页面")
    p_rep.add_argument("result", help="run 产出的结果文件")
    p_rep.add_argument("page", help="HTML 页面输出路径")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        try:
            num, den = _parse_eps(args.eps)
        except ValueError:
            print(
                f"run: 非法 eps {args.eps!r}，应为 <分子>/<分母> 且 0 < 分子 < 分母",
                file=sys.stderr,
            )
            return 1
        return run(args.stream, args.result, num, den)
    return report(args.result, args.page)


if __name__ == "__main__":
    sys.exit(main())
