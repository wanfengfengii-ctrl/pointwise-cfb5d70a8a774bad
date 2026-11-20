# 两张留样单的离线合查

`README.md` 说明已运行的净量交班链。V1 按袋净量独立核对每张单。合查使用单独的 V2 件和签存入口，源库与外站库仍分开。

## 成分与公开边界

发行按指定封定盘点的操作段和封定序位取材。原批的整克量全部属于该批。回混逐批守恒，分装出口只实称净克数，每个出口的原批份额均为非负整数，各批在同一操作的投入和产出总量相等。所有原出口净量同时成立，未选末袋也占用实称的份额。回混后的分装成分由这些条件确定可行范围。

件内证据须恰好表达选袋各批完整成分的联合可行关系。每种原账允许的选袋成分都可在外站使用，每种外站使用的成分也须能补全为原账允许的整克分配。原批号作为对外代号，列出在封定操作图中能沿投入产出关系到达任一选袋的原批，零克投入也按此规则确定相关性。空选袋合法，批代号列表为空。保持具名零克袋和任意精度整数。

对外正文可公开选袋身份、净量、相关原批代号及维持共同兑现资格所需的匿名证据。厂内节点号、操作号、原操作路线和按单个未选袋可直接读取的身份、净量或成分记录留在厂内。共同约束可带其所需的数值与匿名变量。件内证据的具体结构由实现定义，并由同一实现的外站接纳与复核消费。

## Python 调用

- `exchange.issue.issue_joint(db, inventory_id, selected_bags) -> str` 在源库发行 UTF-8 JSON 文本。`selected_bags` 为袋号列表或元组，按传入顺序保留，重复或未知袋号报 `ValueError`，无封定盘点报 `LookupError`。同一盘点与同一有序选袋重办返回原固定正文，采用稳定的 V2 包号。
- `exchange.receive.receive_joint(db, piece_id, inventory_id, body) -> int` 在外站接纳文本或 UTF-8 字节，返回正整数接纳号。校验 JSON、版本、随件标识与正文绑定，以及袋行、批代号和证据自身的结构、整数类型和引用。首次接纳以发行方交付的正文为事实来源。已接纳同包号同正文重投沿用首次接纳号，JSON 空白和对象键次序可不同。有效异正文复用包号抛现有 `PieceConflict`，保持首件。非法件或 V1 正文报 `ValueError`。
- `review.publish.review_joint(db, piece_id, requests) -> dict` 只使用外站已接纳的 V2 件。无可用 V2 件报 `LookupError`。`requests` 是恰好两项的有序列表或元组，每项为 `{"allowed_bags": [袋号, ...], "batch_code": 原批代号, "required_grams": 非负整数}`。允许袋按集合解释，回执中按袋号排序去重。空集合、零克要求合法，仍校验袋号、批代号及字段。未知袋或批、非法请求报 `ValueError`。
- `review.readback.read_joint_review(db, review_id) -> dict | None` 领取签存原结果。未知的正整数号返回 `None`，其他非法号报 `ValueError`。领取使用已存结果，重开后正文与初次签存相同。

V2 正文顶层字段为 `format`（整数 `2`）、`piece_id`、`inventory_id`、`bags`、`batch_codes` 和 `evidence`。`bags` 是按选袋顺序排列的 `[袋号, 净克数]` 数组。`batch_codes` 为无重复的字符串数组，`evidence` 为 JSON 对象。标识及非负整克数沿用 V1 的值域，布尔、小数和空值无效。

签存结果包含 `review_id`、`piece_id`、`inventory_id`、`acceptance_no`、规范化后的 `requests`、`status` 和 `uses`。`uses` 是按两单原序排列的两个数组，每个数组列出该单在包内袋序下的 `[袋号, 正整数取量]`。`satisfied` 时，每单只从许可袋取其指定原批，取足整克数。两单合计从每袋取用的各批克数须同时容纳在同一个可行袋成分中，袋内剩余成分继续计入原账。允许任一满足条件的逐袋账。`short` 表示不存在共同分配，`uses` 为 `[[], []]`。两种结论均签存并返回同一结构。签存固定实际接纳件、两单和结果。每次发行、接纳或复核写入失败时撤销该次写入，异常向调用方传播，恢复后可重试。

## 场景与交付检查

`joint_cases.py` 用 V1 业务入口建立封定盘点。每个同名 `sealed-day` 场景使用独立源库，`build_source(db, name)` 返回该盘点，`CASES[name]["selected"]` 给出发行顺序。下表用“袋集合／原批／克数”表示请求。括号内为结果中的两单实际取量。

| 场景 | 第一单 | 第二单 | 预期 |
| --- | --- | --- | --- |
| `single` | left／A／5 | left／A／5 | `short` |
| `single` | left／A／5 | right／A／5 | `satisfied`（left 5，right 5） |
| `single` | left、right／A／5 | left／A／5 | `satisfied`（right 5，left 5） |
| `mixed` | left／A／5 | right／A／5 | `short` |
| `mixed` | left／A／5 | right／B／5 | `satisfied`（left 5，right 5） |
| `separate` | left／A／5 | right／B／5 | `short` |
| `hidden` | kept／A／2 | kept／A／1 | `short` |
| `hidden` | kept／A／2 | kept／B／5 | `satisfied`（kept 2，kept 5） |
| `shared` | left／A／2 | right／A／2 | `short` |
| `shared` | left／A／2 | other／A／2 | `satisfied`（left 2，other 2） |

`mixed` 与 `separate` 的 V1 袋账相同。`hidden` 的未选袋先从 A 占用 3 g，`kept` 实称 7 g。`shared` 的 left 和 right 共用只含 2 g A 的中间混料，另 2 g A 在 other。运行 `python3 -B joint_cases.py` 可核对夹具本身的 V1 袋账与独立取量。

在源连接关闭后接纳、合查，再重开外站按两种结论的复核号领取。核对同件重投、错绑定和 V1 拒收。对选定的 V2 签存写入点注入 SQLite 写入失败，核对原接纳与已签成果可用、本次无部分签存，解除故障后重试。继续通过原测试及 V1 样例。原 `.pointwise-runtime.json` 的 `verify` 核对原回归和联合业务并保留失败退出码，`demo` 展示实际回混争用、未选袋占量与断源重开结果。沿用清单现有版本和命令格式。
