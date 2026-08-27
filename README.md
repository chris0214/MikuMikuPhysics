# MikuMikuPhysics 2.2

> 本插件使用 GPT-5.5 辅助编写、调试与文档整理。

MikuMikuPhysics 是一个 Blender 4.2+ 插件，用于直接模拟由 mmd_tools 导入的 PMX/MMD 模型刚体物理。插件通过外部 `pmx_bullet.dll` 使用 Bullet 2.82 r2704，不依赖 Blender 内置 Bullet，目标是尽量接近 MMD 与 PMXEditor TransformView 的物理行为。

已在以下版本通过完整回归测试（注册、扫描、实时模拟、烘焙，使用真实 PMX 模型）：

- Blender 4.2 – 4.5（原作者支持范围）
- Blender 5.2.0 LTS（本 fork 实测通过，见 `tests/`）

- 项目地址：<https://github.com/chris0214/MikuMikuPhysics>
- 作者 / 维护者：克里斯提亚娜
- 插件类型：Blender Add-on / Extension
- 许可证：GPL-3.0-or-later
- 插件包名：`MikuMikuPhysics`

## 主要功能

- 直接读取 mmd_tools 导入后的 PMX 模型根对象、骨架、刚体、关节、碰撞组与骨骼绑定。
- 使用外部 Bullet 2.82 native DLL 进行物理解算。
- 实时 Timer 物理预览，不依赖 Blender 时间线播放。
- 时间线模式，支持按帧检查物理结果与 VMD 动作。
- 物理结果烘焙为 Blender 骨骼关键帧。
- 多模型预览：独立世界、影子碰撞、完全共享世界。
- 彩色半透明刚体 / 关节调试可视化。
- 性能统计面板，显示 Bullet、读回、骨骼写回与 depsgraph 刷新耗时。
- 高速拖动保护（Fast Drag Protection），减少拖动模型时的滞后和穿模。
- 姿态模式交互作用域（Interaction Scope），拖动手臂等骨骼时，头发 / 裙摆等无关物理不受影响，行为接近 MMD 本体。
- 针对头发、裙摆、尾巴、链条等结构的名称规则参数。

## 测试

`tests/` 内是运行在 Blender 自带 Python 中的回归测试套件（后台模式 + 真实 PMX 模型），覆盖注册、扫描、实时模拟 tick、时间轴模式、烘焙、烘焙进度回调与性能回归：

```bash
python tests/run_all.py "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"
```

- 每个测试模块在独立 Blender 进程中运行（`tests/run_all.py`），因为同一会话内连续烘焙存在 Blender 层面的浮点不确定性。
- `tests/golden_bake.json` 是优化前烘焙输出的逐位快照；性能优化必须保持与其完全一致（`test_perf.py`）。
- `tests/_capture_golden.py` 用于在有意改变模拟行为时重新生成黄金基线。

## 安装

推荐把 `MikuMikuPhysics` 文件夹作为 Blender 插件安装。目录结构如下：

```text
MikuMikuPhysics/
  __init__.py
  blender_manifest.toml
  config.py
  localization.py
  native/
  operators/
  panels/
  physics/
```

安装方式：

1. 打开 Blender 4.2 或更新版本。
2. 进入 `Edit > Preferences > Add-ons`。
3. 点击 `Install...`，选择打包好的 zip，或把 `MikuMikuPhysics` 文件夹放入 Blender 插件目录。
4. 启用 `MikuMikuPhysics`。
5. 在 3D View 右侧 Sidebar 中打开 `MMP` 面板。

传统插件目录示例：

```text
%APPDATA%\Blender Foundation\Blender\4.2\scripts\addons\MikuMikuPhysics
```

## 使用前准备

本插件不负责导入 PMX 模型。请先安装并启用 mmd_tools，然后：

1. 使用 mmd_tools 导入 PMX 模型。
2. 确认模型在 Outliner 中包含 `armature`、`rigidbodies`、`joints` 等对象。
3. 如需导入动作，可以先用 mmd_tools 导入 VMD，也可以使用本插件面板中的 `Import VMD Motion` 调用 mmd_tools。

注意：

- 开始模拟时，插件会临时停用 Blender 内置 rigid body world，避免双重物理。
- 插件会临时静音 mmd_tools 的物理跟随约束（`mmd_tools_rigid_track`），停止或重置后会恢复。
- 如果刚体 / 关节没有由 mmd_tools 正确创建，插件会提示 `Selected model has no mmd_tools rigid bodies`。

## 快速开始

### 实时预览

1. 选择 PMX 模型根对象，或选择模型下任意对象。
2. 点击 `Use Active Model`。
3. 点击 `Scan Model` 检查刚体、关节、碰撞数据。
4. 选择质量预设：
   - `Preview`：低配视口预览，速度优先。
   - `Default`：默认平衡档。
   - `Mid`：默认 MMD 风格档（120 Hz × 8 substeps），推荐。
   - `Hard`：更强约束、更多子步，适合复杂链条。
5. 点击 `Start` 开始实时模拟。
6. 点击 `Stop` 停止。
7. 点击 `Reset` 恢复开始模拟前捕获的状态。

实时模式使用 Blender Timer，不依赖时间线播放。时间线停止时，物理仍可继续运行。

### 姿态模式拖动（接近 MMD 本体）

打开 `Interaction Response`（推荐 `Immediate`）后：

- 在姿态模式选中需要操作的骨骼（如左肩 / 左腕）。
- 拖动该骨骼时，只有手臂方向的物理跟手；头发、裙摆等无关物理不会被父链矩阵传染而抖动。
- 松开后头发 / 裙摆从当前姿态自然恢复摆动。
- 整个过程中，所有动力学刚体仍在持续模拟，不会被冻结。

如需打开作用域调试，勾选 `Show Interaction Debug`，在面板下查看 `interaction_debug_scope` 当前的骨骼集合。

### 时间线模式

勾选 `Timeline Mode` 后，插件按 Blender 帧变化进行模拟。适合：

- 按帧检查物理结果。
- 与 VMD 动作一起检查指定帧效果。
- 烘焙前做确定性测试。

实时预览和时间线模式不要同时混用。切换模式前建议先停止模拟并重置。

### 多模型

`Multi Model Mode` 控制 `Start All` 的行为：

- `Independent Worlds`：每个模型一个独立 Bullet 世界，最稳定，模型之间不碰撞。
- `Root Isolated`：独立世界兼容模式。
- `Shadow Collision`：默认推荐的多模型碰撞模式。每个模型保留自己的 Bullet 世界，其他模型作为运动学影子碰撞体插入，能够互相碰撞且避免远距离动态岛互相拖拽。
- `Full Shared World`：实验模式。所有模型进入同一个动态 Bullet 世界，物理耦合最强，也最容易相互带动。

建议：

- 多角色但不需要碰撞：`Independent Worlds`。
- 需要角色之间碰撞：`Shadow Collision`（默认）。
- `Full Shared World` 主要用于调试和对比。

### 烘焙

1. 设置 `Start` 和 `End`。
2. 设置 `Preroll`，让物理在写关键帧前先稳定。
3. 根据需要勾选 `Restore After Bake`。
4. 点击 `Bake`。

烘焙会把动态物理骨骼结果写入 Blender 骨骼关键帧。烘焙完成后，可以关闭实时物理并直接播放 Blender 动画。

## 参数建议

### Bullet 设置

- `Fixed Step`：默认 `120 Hz`（接近 MMD 本体）。可选 `60 Hz` / `90 Hz` / `240 Hz`。数值越高越精细，也越慢。
- `Max Substeps`：默认 8。每次 Timer tick 最多补多少个物理步；提高可减少掉步，但会降低视口帧率。
- `Solver Iterations`：约束求解迭代次数。提高可增强稳定性。
- `Gravity / Gravity Scale`：重力方向和倍率。
- `Time Scale`：物理时间倍率。

### 交互响应

`Interaction Response` 控制姿态模式拖动时的实时响应行为：

- `Off`：使用普通定时器步进。
- `Balanced`：拖动后追加一次轻量响应步。
- `Immediate`（推荐）：拖动后追加多次响应步并对作用域内的动态骨刚体执行 snap，几乎零延迟跟手。

`Show Interaction Debug` 打开后可以查看：

- `interaction_debug_kind`：当前判定的交互类型（`POSE` / `TRANSFORM` / `NONE`）。
- `interaction_debug_scope`：当前作用域内的骨骼名。
- `interaction_debug_static_bodies` / `interaction_debug_dynamic_bodies`：作用域影响到的刚体名。

### 高速拖动保护

`Realtime Performance` 中的高速拖动选项用于减少拖动模型时的滞后和穿模：

- `Fast Drag Protection`：总开关。
- `Static Body Compensation`：静态 / 运动学刚体拖动时拆分成更细物理段。
- `Dynamic Bone Compensation`：动态骨刚体拖动时提高自适应分段。
- `Max Drag Segments`：一次快速拖动最多拆成多少段。默认 32，可按性能提高到 48。
- `Extreme Drag Resync`：拖动跳变过大时做一次物理重同步。
- `Resync Threshold`：触发极限重同步的模型空间位移阈值。
- `Clear Velocity On Resync`：重同步时清速度。更稳定，但惯性更弱。

推荐默认：

```text
Fast Drag Protection: On
Static Body Compensation: On
Dynamic Bone Compensation: On
Max Drag Segments: 32
Extreme Drag Resync: On
Resync Threshold: 0.5
Clear Velocity On Resync: Off
```

如果快速拖动仍明显穿模，可以把 `Max Drag Segments` 调到 48，或把 `Resync Threshold` 降到 0.25。

### 性能优化

如果视口帧率很低：

- 质量预设切到 `Preview`。
- 关闭 `Update Rigid Objects`。
- 保持 `Skip Unchanged Bones` 开启。
- 关闭调试可视化。
- 降低 `Solver Iterations` 与 `Max Substeps`。
- 多模型时优先使用 `Independent Worlds` 或 `Shadow Collision`。

性能面板中常见瓶颈：

- `Native Bullet` 高：物理解算本身重，降低子步、迭代或刚体数量。
- `Apply Bones` 高：骨骼写回重，保持跳过未变骨骼开启。
- `Depsgraph` 高：Blender 主线程刷新重，降低视口显示复杂度。
- `Object Writes` 高：关闭 `Update Rigid Objects`。

## 技术设计

插件分为三层：

1. Blender UI / 控制层
   - `config.py`
   - `operators/AddonOperators.py`
   - `panels/AddonPanels.py`

2. Python 同步层
   - `physics/pmx_data_reader.py`
   - `physics/physics_world.py`
   - `physics/physics_sync.py`
   - `physics/bake.py`
   - `physics/hybrid_physics_world.py`
   - `physics/shadow_physics_world.py`
   - `physics/shared_physics_world.py`

3. Native Bullet 物理层
   - `physics/bullet_native.py`
   - `native/pmx_bullet_api.h`
   - `native/pmx_bullet_api.cpp`
   - `native/pmx_bullet.dll`

数据流：

```text
mmd_tools PMX model
  -> pmx_data_reader.read_model()
  -> PmxModelData / RigidBodyData / JointData
  -> ctypes bridge
  -> native/pmx_bullet.dll (Bullet 2.82 r2704)
  -> body transform readback
  -> Pose Bone / rigid object writeback
  -> Blender viewport or baked keyframes
```

核心设计：

- 独立物理引擎：不依赖 Blender 内置 Bullet。
- 模型本地坐标：物理空间以 PMX 模型根对象为基准，模型在场景中移动 / 旋转不会破坏解算。
- 骨骼–物理双向同步：静态刚体每帧从骨骼获取位置，动态 / 动态骨刚体从物理结果回写骨骼。
- Temporal Kinematic 初始化：动态刚体初始化时先以 kinematic 状态对齐骨骼，再恢复 dynamic，减少初始爆炸。
- Timer 实时预览：实时模式独立于 Blender 时间线播放。
- 影子碰撞：多模型碰撞时参考 Babylon-MMD 的 shadow body 思路，减少远距离动态岛互相拖拽。
- 交互作用域：姿态模式拖动时只让用户实际选中 / 激活的骨骼进入作用域，drag protection 仅作用于该作用域，避免父链矩阵传染让无关动力学被牵动。

## 已知限制

- Blender Python 与 depsgraph 刷新存在主线程开销，实时手感无法完全等同 MMD 本体。
- 高速拖动时，离散 Bullet 碰撞仍可能穿模；可通过高速拖动保护缓解。
- 多模型烘焙和完全物理耦合仍属于后续计划。
- `Full Shared World` 是实验模式，不建议作为默认生产流程。
- 交互作用域依赖 Blender 当前选中 / 激活的骨骼。如果在物体模式下拖整根骨架，作用域会回退到旧逻辑。

## 参考与借物说明

本项目实现过程中参考了以下项目或软件的行为、设计和公开代码结构。感谢这些项目的作者与维护者。

- mmd_tools：参考其 PMX 模型数据组织、根对象查找、刚体 / 关节归属、骨骼同步方式。本插件不直接包含 mmd_tools 源码。
  - GitHub：<https://github.com/MMD-Blender/blender_mmd_tools>
  - 原始仓库：<https://github.com/powroupi/blender_mmd_tools>
- Babylon-MMD：参考其多物理世界、`worldId`、rigid body bundle、shadow body、Immediate / Buffered 更新链路等设计。作者：noname0310。
  - 作者 GitHub：<https://github.com/noname0310>
  - 项目 GitHub：<https://github.com/noname0310/babylon-mmd>
- Saba：参考其 MMD/PMX 运行时和 Bullet 物理处理思路。
  - 作者 GitHub：<https://github.com/benikabocha>
  - 项目 GitHub：<https://github.com/benikabocha/saba>
- MMD / MikuMikuDance：作为目标物理行为参考。
- PMXEditor / TransformView：作为模型编辑器内实时物理解算行为参考。
- MMD Bridge：参考其 MMD 本体物理与烘焙流程。
- NexGiMa：参考其 PMX/MMD 物理表现和参数风格。
- MikuMikuDayo：参考其 MMD 模型与物理运行逻辑。
- Bullet Physics：本插件 native 层使用 Bullet 2.82 r2704 进行物理解算。

如开源发布，请同时保留本 README、`LICENSE`、`COPYING`，并遵守各参考项目自身许可证。本文中的"参考"表示行为和架构层面的兼容性研究，不表示这些项目为本插件背书。

## 更新日志

### 2.2.0

- 修复姿态模式拖动手臂时头发 / 裙摆等无关物理被牵动的问题。原因是单模型 `PhysicsWorld` 未暴露 `root` 属性，导致交互作用域链路在单模型路径下失效，回退到"任意骨骼矩阵变化"的全局判定，被父链传染的远端骨骼也被算进作用域并触发 drag protection。
- 修复拖动手臂导致下游 STATIC 锚点（手肘 / 手 / 手指）滞后引发的"骨骼炸开"问题。所有 STATIC 刚体每帧都跟随当前骨骼矩阵，作用域只用于约束 drag protection。
- 修复使用作用域时部分动力学刚体被冻结导致头发 / 裙摆"卡住"的问题。作用域外的动力学保持自由模拟，整个流程接近 MMD 本体的"拖一边、其他依然在跑"。
- 修复作用域为空集时所有 STATIC 被锁死的边界情况，例如选中 IK 控制骨等未绑刚体的骨骼。
- `_iter_world_roots` 增加从 `world.model` / `world.models` 派生 root 的兜底逻辑，避免后续新世界类未暴露 `root` 又再次出现作用域失效。
- 默认 `Multi Model Mode` 由 `Root Isolated` 改为 `Shadow Collision`，开箱即获得多模型互相碰撞。
- 默认 `Fixed Step` 由 `60 Hz` 改为 `120 Hz`，`Max Substeps` 由 `2` 改为 `8`，更接近 MMD 本体的精度，并改善大幅拖动时裙摆 / 头发"摆动变弱"的现象。
- 文档同步更新。

### 2.1.0

- 新增 `Apply All Debug Visuals`，可同时显示多模型列表中所有启用模型的彩色半透明刚体 / 关节预览。
- 新增 `Interaction Response` 交互即时响应模式，提供保守的 `Balanced` 选项，用于降低拖动模型或骨架时的实时物理滞后。

### 2.0.0

- 插件包名改为 `MikuMikuPhysics`，Blender N 面板标签缩写为 `MMP`。
- 使用外部 Bullet 2.82 r2704 DLL 进行 PMX/MMD 刚体与关节模拟。
- 支持实时 Timer 物理预览、时间线模式、单步、停止、强制停止与重置。
- 支持 mmd_tools PMX 刚体 / 关节读取、VMD 导入入口和物理烘焙。
- 支持多模型模拟：独立世界、影子碰撞、共享世界等模式。
- 增加高速拖动保护、极限重同步、静态 / 动态骨补偿等交互稳定化选项。
- 增加彩色半透明物理调试可视化与性能统计面板。
- 整理 README、GPL 许可证、参考项目与借物说明，作为首次公开版本。

## 后续计划

- 更完善的多模型碰撞烘焙。
- 更细粒度的性能模式和视口降级策略。
- 更完善的物理结果对比工具。
- 把交互作用域的"用户选中骨骼判定"扩展到物体模式下的整骨架拖动。
