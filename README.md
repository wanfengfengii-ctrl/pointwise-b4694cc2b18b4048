# 校准检测室仪器读数归档

控制器交来定宽字与原卷清单。登记员封存原件和初版，质检员办理勘误，夜班用现行值、出处、固定定稿与字盘核账交班。工程使用 Python 3.11 标准库与本地 SQLite 文件。

```text
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B demo.py
```

`check_project.py` 由运行环境提供。演示使用临时数据库，以相同样例分别办理续成和撤销，校验后输出实测读数、出处和实物字。

## Python 接口

以下入口接受 SQLite 文件路径。先调用 `intake.register.initialise_archive(path)`。重复初始化保留已登记的布局、实物字、用户勘误及定稿。显式调用演示才装载样例。

| 入口 | 参数与返回 |
| --- | --- |
| `layout.registry.define` | `path, LayoutSpec`。返回布局号。`LayoutSpec` 接受布局号、字宽、每行字数和有序的 `FieldSpec`。字段定义依次为名称、零起字槽、最低位偏移、位宽、可选缺测码。 |
| `intake.register.ingest` | `path, volume_id, layout_id, rows, manifest`。`InputRow` 依次包含行名、正整数页号、正整数页内位置、定宽字序列。`ManifestEntry` 依次包含行名、字数、页号、页内位置。返回含初版号的 `AcceptanceReceipt`。 |
| `corrections.request.amend` | `path, volume_id, request_id, changes, *, hook=None`。每项改值为 `(row_id, field_name, reading)`，原请求参数按目标与值比较，输入排列可变。返回 `CorrectionReceipt` 或同号原撤销结果。 |
| `corrections.recover.resume` | `path, request_id, *, action='continue', hook=None`。`action='cancel'` 选择撤销未发布请求。同号重开可续成、续清理或复领终局。 |
| `delivery.current.current` | `path, volume_id, fields=None, *, hook=None`。可选字段名序列，返回有序 `FieldObservation` 元组，每项带页位、字槽及原件或发布出处。 |
| `delivery.snapshot.frozen` | `path, report_id`。返回 `FixedReport`，包含原正文及签发时的凭证。接纳初版包含全卷，勘误定稿包含本单签认的观测。 |
| `delivery.reconcile.reconcile` | `path, volume_id, *, hook=None`。返回逐字核账，含预期字、实物字、逐字段判断、未定义位差异、最近的实物操作和待办请求。 |

字与数值使用无符号整数，按仪器原刻度精确存取。`layout.values.MISSING` 表示缺测，合法的整数零照常返回。数字超宽、负数、布尔值或与缺测码相同的数字被拒绝。位段不得相交。选取字段后仍按原行序、布局字段序返回。每个页位和原行名在卷内唯一，清单须按输入原序逐项一致。同号同一布局或同一原件可重交并复领原结果。

输入不合法返回 `ValueError`，同号异定义、异原件、异参及已发布撤销返回其子类 `ConflictError`。未知卷、布局、请求、输入所引用的行或字段及未知定稿可返回 `NotFound`。重叠请求由 `FieldsBusy` 给出占用者。首字落盘前后、发布前后可以通过 `hook(event, detail)` 控制交班的确定次序。收到 `ReplyLost` 时按原号续办，发布结果以持久记录为准。现行查询的 `after_observation` 发生在固定读截面内。核账读取点 `before_word_read` 遇到 `WordUnavailable` 会列为待查。成功首执证明发布，字盘结清情况通过核账确认。

## 工作日样例

布局有两个 8 位字，首字低三位为 x、自第 3 位起三位为 z，次字低三位为 y，三个字段的缺测码均为 7。编号靠前的原行在样例中后交，报告沿用提交顺序。第一行原字为 17 和 3，得到 `(1, 3, 2)`。甲单改 x、y，首字已写为 20 时失答。乙单同字修改 z 后，实物首字为 52，持有乙单出处的现行组为 `(1, 3, 6)`。重开续成甲单后交付 `(4, 5, 6)`。另一卷从相同暂停点撤销甲单，实物首字为 49，交付 `(1, 3, 6)`，乙单首执和出处均保留。两卷均可核账，并复领最初的原件定稿。
