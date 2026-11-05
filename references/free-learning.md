# 自由学习与模式切换

## 识别意图

“我想自由安排学习计划”“我想自由按需学习”“有空就学”“不按顺序学”“自由浏览所有章节”“切换到自由模式”等表达选择自由学习。用户明确要求切换时直接执行，不重复询问是否确认。仅说“不确定每天学多久”时，提供自由学习选项，不强行假定每天 30 分钟。

两种设置独立：

- `meta.json.mode`：课程讲解方式，仍为 `speedrun` / `system` / `interview` / `exam`。
- `meta.json.learning_mode`：学习方式，`guided`（按进度学习）或 `free`（自由学习）。旧课程缺少字段时按 `guided` 读取。

新课程仍需确认目标、基础、材料和存放目录，完成调研、生成和课程审查；选择自由学习不会生成一套不同深度的课程。未指定讲解方式时仍询问精讲、速成、面试或考试需求。接受“不固定每天时长、无完成期限”，按知识关系组织章节，路线图显示“自由安排”，不按天分配任务、不要求连续打卡。没有每日预算时 `profile.json.preferences.daily_time_budget_minutes` 可为 `null`，保留已有全局偏好时只需把本课程的自由安排约束写进画像。

## 切换已有课程

使用确定的课程状态目录：

```bash
python {skill_dir}/scripts/set-learning-mode.py "{learning_root}/.learning-profile/courses/{course_slug}" free
python {skill_dir}/scripts/set-learning-mode.py "{learning_root}/.learning-profile/courses/{course_slug}" guided
```

播放器左侧的“学习方式”选择框提供相同切换，无需 Agent。切换持久化到课程的 `meta.json`，下次直接打开也会保留；只读播放器不能切换。

切换仅改变 `learning_mode`，保留 `mode`、`mode_label`、`params.json`、`current_module`、`completed_modules`、技能节点状态、XP 和成就。不把 `locked` 批量改为 `available`，不把章节标成已掌握。

两份记录各自保存浏览位置、作答、待问问题和已读页：

| 学习方式 | 记录 |
| --- | --- |
| guided | `learning-record.json`，保留原有学习进度 |
| free | `free-learning-record.json`，首次作答/浏览时创建 |

切回 `guided` 后使用原记录恢复位置与解锁情况；再次进入 `free` 时继续自由学习记录。切换不会删除任意一份记录，不需要复制或回滚整套状态。

## 自由学习中的 Agent 行为

- 所有已生成模块和小节均可打开，前置知识只作为建议。不要自动把用户带回先修章节；用户未指定章节时，使用自由学习的停留位置，或请其从目录选择。
- 不要求每天学多久、不要求完成练习才能换章节；可直接标记本页已读，练习按需提交。
- 读取 `free-learning-record.json` 回答问题和评阅作答，并在同一文件清除已回答问题。
- 自由学习的已读和作答不自动写入主线 `current_module`、`completed_modules`、技能节点、XP、成就或连续学习统计。正式进度保留到切回 `guided` 后按原掌握门槛评估；不要把自由记录自动合并进去。
- 已有知识点的复习排期可继续使用；用户主动评分仍更新同一份 `concepts.json`，这是实际复习行为，不会解锁主线。默认不以到期复习阻止按需阅读。
- 原模式的教学参数保留，单纯切换不改变深度、题量或掌握门槛。用户另外要求修改讲解方式或课程时，再走对应流程。

## 独立打开播放器

已有课程可直接启动，无需运行 Agent：Windows 双击 `{skill_dir}/open-player.cmd`；macOS/Linux 运行 `sh {skill_dir}/open-player.sh`。默认学习目录是 `~/learning`，自定义目录用 `--learning-root` 指定。省略 `--course` 会显示“我的课程”，进入课程后可在页面切换学习方式。完整参数见 `learning-viewer.md`。

课程生成和 AI 答疑仍由 Agent 完成；播放器可独立阅读、显示参考解析、保存作答与问题，但不会自行调用模型或评定掌握度。
