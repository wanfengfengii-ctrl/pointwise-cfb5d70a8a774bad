# 岚溪散料试验中心净量交班账

岚溪中心记录实际收料和分装净重。仓边资料员使用称量单固定原批身份，操作员登记各出口，盘点员逐袋对实盘。河西合作复核站收到封定盘点的净量包后核对一张留样单，次日按复核号复领取样指引。源库和外站库独立保存。

## 运行

在项目根目录使用 Python 3.11 标准库。控制台提供标准回归入口。

```sh
python3 -B check_project.py
python3 -B demo.py
```

直接运行完整 unittest 套件可用 `python3 -B -m unittest discover -s tests -t . -v`。样例读取 `samples/weighings.json` 和 `samples/workday.json`，使用两份临时 SQLite 库。它把 7 g 和 3 g 回混为 10 g，再分装为两只 6 g、4 g 袋。外站在源库关闭后签存 8 g 申请，重开后读回按袋序取 6 g、2 g 的原回执。

## 一天的交班

1. 资料员实收台秤称量单，记录原批、净量与首执。导入记录还保存来源及一基行位，行位是 JSON 数组中的记录序号。
2. 操作员开段，登记多个已可用投入回混为一个实称出口。
3. 操作员从一个可用节点分装多个实称出口。校验身份与守恒后，操作、耗用与产出同次提交。
4. 盘点员录入实盘，系统按已提交操作重放完整末袋，并列出缺袋、额外袋和实盘减账面的克差。
5. 实盘相合时固定原序位及排序后的袋账，同时关闭操作段。有差异时可以更正实盘再提交。
6. 发行员按明确盘点号签发固定净量包，后续可按原号复领。
7. 外站验证随件标识和正文绑定，持久保存实际接纳版本。
8. 复核员提交允许袋及所需克数。按包序取量，每袋最多贡献本袋净量，满足后结束。不足时也保留已取量和缺口。
9. 外站一并签存采用包、要求、取量、状态与回执。次班读取持久结果。

## Python 接口

| 模块 | 业务入口和返回值 |
| --- | --- |
| `storage` | `open_source(path)`、`open_station(path)` 返回各自的 SQLite 连接。`initialize_source(db)`、`initialize_station(db)` 可在空闲连接上重复执行并保留业务记录。用 `close()` 或 `contextlib.closing` 关闭连接。 |
| `intake.batches` | `receive_batch(db, batch_id, net_grams, ticket_id)` 实收并返回 `RawBatch` 及首执。`get_batch(db, batch_id)` 按批号读取，未知时返回 `None`。 |
| `intake.imports` | `import_weighings(db, path, source=...)` 逐笔接纳本地称量数组，返回按原行序排列的实收和拒收。缺省出处使用文件名。 |
| `handling.segments` | `open_segment(db, segment_id)` 建立或读取操作段。再次调用可读取已关闭状态。 |
| `handling.operations` | `record_operation(db, segment_id, operation_id, kind, inputs, outputs)` 返回有序操作。`kind` 为 `mix` 或 `split`，投入为节点号，产出为 `(节点号, 整克数)`。`load_operation_log` 可按段和可选上限 `through_sequence` 读取操作与实际投入原批。 |
| `inventory.close` | `close_inventory(db, segment_id, observations, inventory_id=...)` 接收 `(袋号, 整克数)` 序列，返回 `CloseResult`。盘点号缺省取段号。 |
| `inventory.readback` | `read_inventory(db, inventory_id)` 返回固定盘点，未知时返回 `None`。 |
| `exchange.issue` | `issue_totals(db, inventory_id)` 返回固定 `TotalsPiece`，包号由 `totals:` 和盘点号组成。未知或未封定盘点报 `LookupError`。 |
| `exchange.format` | `encode_totals(piece)` 返回 JSON 正文，`decode_totals(body)` 读取正文。 |
| `exchange.receive` | `receive_totals(db, piece_id, inventory_id, body)` 首次接纳或返回原接纳号。同号异内容报 `PieceConflict`。 |
| `exchange.readback` | `read_issued_totals`、`read_issued_totals_for_inventory` 和 `read_accepted_totals` 从各自所属库读取固定件。未知件返回 `None`。 |
| `review.publish` | `review_total(db, piece_id, allowed_bags, required_grams)` 返回 `StoredReview`，状态为 `satisfied` 或 `short`。 |
| `review.readback` | `read_review(db, review_id)` 领取原件、原要求、用量、结论和回执。未知正整数号返回 `None`。 |

克数必须是非负整数。小数、布尔值、空值和缺项会报 `ValueError`。SQLite 数量列使用十进制文本，业务运算使用 Python 整数。具名零克袋参加对账，空段也可封定。所有具名字段保留原字符串，袋账按字符串码点排序。允许袋按集合解释，零克要求仍会检查每个允许袋。只持久保存正取量。

同批号、同克数和同称量单返回首收回执。改克数或称量单报 `BatchConflict`，并保留冲突记录和原首收。原批全库只能投用一次，产出身份按段查找，段内的历史产出名不能再作新产出，已登记的原批名也保留给原批。实盘重复袋号会在比较前拒绝。合法盘差报告保持操作段开放。签存使用已接纳件，未知件报 `LookupError`，未知袋报 `ValueError`。写入错误会传播，由入口事务撤销本次业务写入。低层保存函数用于调用方已经开始的写事务。

V1 正文包含 `format`、`piece_id`、`inventory_id` 和顺序固定的 `bags`。接纳会校验随件标识与正文绑定以及袋行合法性。独立核对多张单时，每张单都使用原包净量。签存的取样指引不会扣减下一张单可核对的包净量。
