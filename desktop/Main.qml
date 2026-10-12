import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: window
    width: 1280; height: 800; minimumWidth: 1024; minimumHeight: 680
    visible: true; title: "WeChat MCP Desktop — Stellaria AXR"
    color: Theme.canvas
    palette.window: Theme.surface; palette.windowText: Theme.ink; palette.text: Theme.ink; palette.base: Theme.surface; palette.button: Theme.surface; palette.buttonText: Theme.ink; palette.highlight: Theme.brand; palette.highlightedText: "white"
    font.family: Qt.platform.os === "osx" ? "PingFang SC" : "Microsoft YaHei UI"
    font.pixelSize: Theme.body
    property int page: 0
    property bool darkMode: false
    property string selectedConversation: ""
    property string selectedLabel: ""
    property var tabs: ["工作台", "Agent 连接", "消息与草稿", "权限中心", "执行记录", "附件与内容", "设置"]
    property var glyphs: ["grid", "plug", "inbox", "shield", "activity", "clip", "settings"]
    property var backend: owner.data || ({})
    property var status: window.backend.status || ({})
    property var listener: status.listener || ({})
    property var platform: status.platform || ({})
    property bool previewMode: window.backend.scope === "synthetic_preview"
    property bool connected: window.backend.connected === true && !previewMode
    property var drafts: window.backend.drafts || []
    property var jobs: window.backend.jobs || []
    property var pending: jobs.filter(function(j){return ["Ready","AwaitingApproval","Executing","Prepared","Verifying"].indexOf(j.state)>=0 && j.expires*1000>Date.now()})
    property var recent: jobs.slice(0,6)
    property var intent: (owner.preview || {}).intent || ({})
    property var exactDisclosure: (owner.preview || {}).exact_disclosure || ({})
    property bool sendAvailable: !previewMode && platform.send_available === true
    Binding { target: Theme; property: "dark"; value: window.darkMode }
    function operation(op){return ({"messages.read":"读取消息","messages.search":"搜索消息","files.read":"解析本地附件","reply.prepare":"生成回复草稿","disclosure.send":"内容披露审批","messages.send":"提交微信回复","workspace.write":"保存工作文档","application.navigate":"应用导航","expired":"已过期任务"})[op] || "处理任务"}
    function stateLabel(state){return ({"AwaitingApproval":"等待你的批准","Ready":"等待执行","Executing":"正在处理","Prepared":"已准备","Verifying":"核验结果","Completed":"已完成","Unknown":"结果待核对","FailedSafe":"已安全停止","Expired":"已过期","Cancelled":"已取消","Denied":"已拒绝","Proposed":"待检查","PolicyChecked":"已检查权限"})[state] || "待验证"}
    function destinationLabel(value){return value === "local" ? "仅本机" : value === "model:codex" ? "Codex" : value && value.indexOf("wechat:")===0 ? "指定微信会话" : value && value.indexOf("model:")===0 ? "模型：" + value.slice(6) : value || "—"}
    function targetName(cid){var list=window.backend.conversations || [];for(var i=0;i<list.length;i++)if(list[i].conversation_id===cid)return list[i].display_name;return cid || "本地操作"}
    function timeLabel(value){return value ? new Date(value*1000).toLocaleString(Qt.locale(),"MM-dd HH:mm") : "—"}
    function grantsFor(cid){return (window.backend.grants || []).filter(function(g){return g.conversation_id===cid})}
    function permitted(cid,op){return grantsFor(cid).some(function(g){return g.operations.indexOf(op)>=0 && g.remaining>0})}

    component Copy: Text { color: Theme.ink; textFormat: Text.PlainText; wrapMode: Text.WordWrap; font.pixelSize: Theme.body }
    component Caption: Copy { color: Theme.muted; font.pixelSize: Theme.caption }
    component ButtonX: Button {
        id: control
        property bool primary: false
        property bool danger: false
        implicitHeight: 36; leftPadding: 14; rightPadding: 14
        focusPolicy: Qt.StrongFocus
        Accessible.name: text
        Keys.onReturnPressed: control.clicked()
        Keys.onEnterPressed: control.clicked()
        background: Rectangle { radius: Theme.controlRadius; color: control.primary ? Theme.brand : control.hovered ? Theme.hover : Theme.surface
            border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? Theme.positive : control.primary ? "transparent" : Theme.border; opacity: control.enabled ? 1 : .42 }
        contentItem: Text { text: control.text; color: !control.enabled ? Theme.muted : control.primary ? "white" : control.danger ? Theme.danger : Theme.ink
            textFormat: Text.PlainText; font: control.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    }
    component Panel: Rectangle { color: Theme.surface; radius: Theme.radius; border.color: Theme.border }
    component Badge: Row {
        property string text: ""
        property string symbol: "info"
        property color ink: Theme.muted
        spacing: 6
        Icon { name: parent.symbol; ink: parent.ink; width: 15; height: 15; anchors.verticalCenter: parent.verticalCenter }
        Caption { text: parent.text; color: parent.ink }
    }
    component Empty: RowLayout {
        property string heading: "暂无待处理事项"
        property string explanation: "新消息触发的草稿与审批会显示在这里。"
        property string symbol: "inbox"
        implicitHeight: 76; spacing: 14
        Icon { name: parent.symbol; ink: Theme.muted; width: 24; height: 24 }
        ColumnLayout { Layout.fillWidth: true; spacing: 7
            Copy { Layout.fillWidth: true; text: parent.parent.heading; font.weight: Font.Medium }
            Caption { Layout.fillWidth: true; text: parent.parent.explanation }
        }
    }
    component JobRow: Rectangle {
        required property var job
        property bool compact: false
        implicitHeight: compact ? 62 : 76; radius: 9; color: Theme.canvas
        RowLayout { anchors.fill: parent; anchors.margins: 14; spacing: 12
            Icon { name: job.state === "Completed" ? "check" : job.state === "Unknown" ? "warning" : "clock"; ink: job.state === "Completed" ? Theme.positive : Theme.muted; width: 19; height: 19 }
            ColumnLayout { Layout.fillWidth: true; spacing: 5
                Copy { Layout.fillWidth: true; text: window.operation(job.operation) + (job.target ? " · " + job.target : ""); font.weight: Font.Medium; maximumLineCount: 1; elide: Text.ElideRight }
                Caption { Layout.fillWidth: true; text: window.stateLabel(job.state) + "  ·  " + window.timeLabel(job.created) }
            }
            ButtonX { visible: !compact; text: "核对详情"; onClicked: {owner.review(job.id);intentDialog.open()} }
            ButtonX { visible: !compact && ["Ready","AwaitingApproval"].indexOf(job.state)>=0; text: "执行"; enabled: !window.previewMode; onClicked: owner.execute(job.id) }
        }
    }
    component PageScroll: ScrollView { clip: true; contentWidth: availableWidth; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            objectName: "sidebar"; Layout.preferredWidth: Theme.sidebarWidth; Layout.fillHeight: true; color: Theme.sidebar
            Rectangle { anchors.right: parent.right; height: parent.height; width: 1; color: Theme.border }
            ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 5
                RowLayout { Layout.fillWidth: true; Layout.topMargin: 18; Layout.bottomMargin: 28; spacing: 12
                    Rectangle { width: 36; height: 36; radius: 10; color: Theme.brand; Icon { anchors.centerIn: parent; name: "message"; ink: "white"; width: 23; height: 23 } }
                    Column { spacing: 4
                        Copy { text: "WeChat MCP"; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Caption { text: "Desktop"; font.pixelSize: 12 }
                    }
                }
                Repeater { model: window.tabs
                    delegate: Button {
                        id: nav
                        objectName: "nav" + index
                        required property string modelData; required property int index
                        Layout.fillWidth: true; Layout.preferredHeight: 41
                        focusPolicy: Qt.StrongFocus; Accessible.name: modelData
                        Keys.onReturnPressed: nav.clicked()
                        Keys.onEnterPressed: nav.clicked()
                        background: Rectangle { radius: 9; color: window.page===nav.index ? Theme.tint : nav.hovered ? Theme.hover : "transparent"
                            border.color: nav.activeFocus ? Theme.positive : "transparent"; border.width: nav.activeFocus ? 2 : 0 }
                        contentItem: RowLayout { spacing: 11
                            Icon { name: window.glyphs[nav.index]; ink: window.page===nav.index ? Theme.positive : Theme.muted; width: 19; height: 19; Layout.leftMargin: 12 }
                            Copy { Layout.fillWidth: true; text: nav.modelData; color: window.page===nav.index ? Theme.ink : Theme.muted; font.weight: window.page===nav.index ? Font.DemiBold : Font.Normal }
                        }
                        onClicked: window.page=index
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                Caption { Layout.topMargin: 16; text: "Powered by"; font.pixelSize: 11 }
                Copy { text: "Stellaria AXR"; font.pixelSize: 16; font.weight: Font.Medium }
                Caption { text: "授权清晰，行动可追溯。"; font.pixelSize: 11; Layout.bottomMargin: 14 }
            }
        }
        ColumnLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 88; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin
                Column { spacing: 5
                    Copy { text: window.tabs[window.page]; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
                    Caption { text: ["你的 Agent 工作概览", "连接与协议诊断", "聚焦需要处理的消息", "按资源掌握每一项授权", "以真实执行回执为依据", "处理微信中已缓存的文件", "你的桌面工作环境"][window.page] }
                }
                Item { Layout.fillWidth: true }
                BusyIndicator { running: window.backend.loading === true; visible: running; implicitWidth: 22; implicitHeight: 22 }
                ButtonX { text: "刷新"; enabled: window.backend.loading !== true; onClicked: owner.refresh() }
            }
            StackLayout { id: pages; objectName: "contentViewport"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin; currentIndex: window.page
                PageScroll {
                    contentHeight: overview.implicitHeight
                    ColumnLayout { id: overview; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 106
                            RowLayout { anchors.fill: parent; anchors.margins: 22; spacing: 14
                                Icon { name: window.previewMode ? "info" : window.connected ? "check" : "plug"; ink: window.previewMode ? Theme.warning : window.connected ? Theme.positive : Theme.muted; width: 24; height: 24 }
                                ColumnLayout { Layout.fillWidth: true; spacing: 9
                                    Copy { Layout.fillWidth: true; text: window.previewMode ? "演示模式 · 未连接真实微信数据" : window.connected ? "本地服务已连接" : "连接你的本地工作台"; font.pixelSize: 17; font.weight: Font.DemiBold }
                                    Caption { Layout.fillWidth: true; text: window.previewMode ? "以下仅为界面预览，真实数据与授权操作已停用。" : (window.listener.listen ? "消息监听已请求" : "消息监听已关闭") + " · " + (window.sendAvailable ? "自动发送需精确授权" : "当前平台暂不支持自动发送") }
                                }
                                ButtonX { text: window.connected ? "管理权限" : "启动本地服务"; primary: true; enabled: !window.previewMode; onClicked: window.connected ? window.page=3 : owner.start() }
                            }
                        }
                        RowLayout { Layout.fillWidth: true; spacing: Theme.gap
                            Panel { Layout.fillWidth: true; implicitHeight: 156
                                ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 14
                                    RowLayout { Layout.fillWidth: true; Copy { text: "待处理事项"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
 Item { Layout.fillWidth: true }
 Caption { text: String(window.pending.length+window.drafts.length) + " 项" } }
                                    Empty { Layout.fillWidth: true; visible: !window.pending.length && !window.drafts.length }
                                    RowLayout { visible: window.pending.length || window.drafts.length; Layout.fillWidth: true
                                        Badge { text: window.pending.length + " 项审批 / 执行"; symbol: "shield"; ink: Theme.warning }
                                        Badge { text: window.drafts.length + " 份回复草稿"; symbol: "message"; ink: Theme.positive }
                                        Item { Layout.fillWidth: true }
                                        ButtonX { text: "处理事项"; onClicked: window.page=window.pending.length ? 4 : 2 }
                                    }
                                }
                            }
                            Panel { visible: window.width>=1320; Layout.preferredWidth: 270; Layout.fillHeight: true
                                ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 12
                                    Badge { text: "权限概览"; symbol: "shield"; ink: Theme.positive }
                                    Copy { text: (window.backend.grants || []).length + " 项有效授权"; font.pixelSize: 21; font.weight: Font.Medium }
                                    Caption { Layout.fillWidth: true; text: "内容披露与本地访问分别批准。" }
                                    Item { Layout.fillHeight: true }
                                }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: activity.implicitHeight+44
                            ColumnLayout { id: activity; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 14
                                RowLayout { Layout.fillWidth: true; Copy { text: "最近活动"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
 Item { Layout.fillWidth: true }
 ButtonX { text: "全部记录"; onClicked: window.page=4 } }
                                Empty { Layout.fillWidth: true; visible: !window.recent.length; heading: "还没有执行记录"; explanation: "任务开始后，授权检查、执行与结果核验会在这里更新。"; symbol: "activity" }
                                Repeater { model: window.recent.slice(0,4); delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData; compact: true } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: notes.implicitHeight+44
                            ColumnLayout { id: notes; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 14
                                RowLayout { Layout.fillWidth: true; Copy { text: "工作摘要"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
Item { Layout.fillWidth: true }
ButtonX { text: "读取已授权摘要"; enabled: window.connected; onClicked: owner.summaries() } }
                                Caption { Layout.fillWidth: true; visible: !(window.backend.summaries || []).length; text: "当前没有有效摘要。过期内容不会继续展示，建议事项也不会自动变为执行权限。" }
                                Repeater { model: window.backend.summaries || []; delegate: ColumnLayout { required property var modelData; Layout.fillWidth: true; spacing: 7
                                    Copy { Layout.fillWidth: true; text: modelData.summary }
                                    Caption { text: "来源：" + modelData.text_records + " 条获准文本 · " + (modelData.has_more ? "仍有后续分页" : "当前页已结束") }
                                } }
                            }
                        }
                        Item { Layout.preferredHeight: 18 }
                    }
                }
                PageScroll {
                    contentHeight: agentPage.implicitHeight
                    ColumnLayout { id: agentPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 162
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                RowLayout { Layout.fillWidth: true; Icon { name: "plug"; ink: Theme.positive }
Copy { text: "OpenAI Codex"; font.pixelSize: 20; font.weight: Font.DemiBold }
Item { Layout.fillWidth: true }
Badge { text: window.backend.worker_state === "running" ? "草稿进程运行中" : "草稿进程未启动"; symbol: "clock" } }
                                Caption { Layout.fillWidth: true; text: "安装本机 MCP 配置，再按需授予会话访问。连接协议通过不等于微信内容已授权。" }
                                RowLayout { ButtonX { text: "核对安装配置"; primary: true; enabled: !window.previewMode; onClicked: {owner.configPreview();configDialog.open()} }
ButtonX { text: "测试 MCP 连接"; enabled: !window.previewMode; onClicked: {owner.testConnection();technicalDialog.open()} } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 174
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                Copy { text: "受控草稿 Agent"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "启动一个全新的、最长 10 分钟的 Codex 会话。它只能处理已批准的消息任务，没有 Shell、浏览器、权限签发或发送工具。" }
                                RowLayout { ButtonX { text: "启动草稿 Agent"; primary: true; enabled: window.connected && window.backend.worker_state !== "running"; onClicked: owner.startAgent() }
ButtonX { text: "查看消息任务"; onClicked: window.page=2 } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 138
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 13
                                Copy { text: "安装与恢复"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "只更新 wechat_axr 配置；其他设置保留。安装前备份，恢复前再次核对，避免覆盖你后续的修改。" }
                                ButtonX { text: "恢复安装前配置"; enabled: !window.previewMode; onClicked: owner.restoreConfig() }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: messagePage.implicitHeight
                    ColumnLayout { id: messagePage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 80
                            RowLayout { anchors.fill: parent; anchors.margins: 22; Icon { name: "message"; ink: Theme.positive }
                                Copy { Layout.fillWidth: true; text: "消息 → 访问检查 → 披露批准 → Agent 草稿 → 结果核对"; font.weight: Font.Medium }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: draftContent.implicitHeight+44
                            ColumnLayout { id: draftContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 14
                                Copy { text: "回复草稿"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Empty { Layout.fillWidth: true; visible: !window.drafts.length; heading: "暂无有效草稿"; explanation: "只显示当前授权及有效期内的结果，不保留过期聊天正文。"; symbol: "message" }
                                Repeater { model: window.drafts; delegate: Rectangle { required property var modelData; Layout.fillWidth: true; implicitHeight: 76; radius: 9; color: Theme.canvas
                                    RowLayout { anchors.fill: parent; anchors.margins: 14
                                        ColumnLayout { Layout.fillWidth: true; spacing: 6
                                            Copy { Layout.fillWidth: true; text: modelData.display_name; font.weight: Font.Medium; maximumLineCount: 1; elide: Text.ElideRight }
                                            Caption { text: "有效至 " + window.timeLabel(modelData.expires) + " · 当前发送模式由授权决定" }
                                        }
                                        ButtonX { text: "查看草稿"; enabled: !window.previewMode; onClicked: {owner.draft(modelData.job_id);draftDialog.open()} }
                                    }
                                } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: taskContent.implicitHeight+44
                            ColumnLayout { id: taskContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 14
                                Copy { text: "正在处理与待审批"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Empty { Layout.fillWidth: true; visible: !window.pending.length; heading: "没有等待审批的任务"; explanation: "新的读取或披露请求会单独显示，正文外发不会混入普通设置。"; symbol: "shield" }
                                Repeater { model: window.pending; delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData } }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: permissionPage.implicitHeight
                    ColumnLayout { id: permissionPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        RowLayout { Layout.fillWidth: true; spacing: 20
                            Badge { text: "策略版本 " + (window.status.policy_version || "—"); symbol: "shield"; ink: Theme.positive }
                            Caption { text: "访问、披露与发送分别授权"; Layout.fillWidth: true }
                            ButtonX { text: "撤销全部授权"; danger: true; enabled: window.connected; onClicked: revokeDialog.open() }
                        }
                        Panel { Layout.fillWidth: true; visible: !(window.backend.conversations || []).length; implicitHeight: 122; Empty { anchors.fill: parent; anchors.margins: 22; heading: "还没有绑定会话"; explanation: window.previewMode ? "演示模式不会创建真实权限。" : "请先完成本机账号与会话的所有者初始化。"; symbol: "lock" } }
                        Repeater { model: window.backend.conversations || []; delegate: Panel {
                            required property var modelData
                            property var grants: window.grantsFor(modelData.conversation_id)
                            Layout.fillWidth: true; implicitHeight: resourceContent.implicitHeight+44
                            ColumnLayout { id: resourceContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 16
                                RowLayout { Layout.fillWidth: true; Icon { name: "message"; ink: Theme.positive }
                                    Copy { Layout.fillWidth: true; text: modelData.display_name; font.pixelSize: 17; font.weight: Font.DemiBold; maximumLineCount: 2; elide: Text.ElideRight }
                                    Badge { text: grants.length ? "有有效授权" : "需要授权"; symbol: grants.length ? "check" : "lock"; ink: grants.length ? Theme.positive : Theme.muted }
                                }
                                RowLayout { Layout.fillWidth: true; spacing: 30
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6; Caption { text: "本地消息与草稿" }
Copy { text: window.permitted(modelData.conversation_id,"messages.read") ? "已限时授权" : "未授权" } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6; Caption { text: "发送给模型分析" }
Copy { text: window.permitted(modelData.conversation_id,"disclosure.send") ? "当前精确批次获准" : "每批需确认" } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6; Caption { text: "自动发送消息" }
Copy { text: window.sendAvailable ? "需独立精确授权" : "当前平台暂不支持"; color: Theme.muted } }
                                }
                                Repeater { model: grants; delegate: Caption { required property var modelData; Layout.fillWidth: true
                                    text: "截止 " + window.timeLabel(modelData.expires) + " · 剩余 " + modelData.remaining + " 次 · " + (modelData.exact_intent ? "精确单次意图" : "本地限定范围") + " · 目的地：" + (modelData.destinations.length ? modelData.destinations.map(window.destinationLabel).join("、") : "仅本机")
                                } }
                                RowLayout { Layout.fillWidth: true
                                    Caption { Layout.fillWidth: true; text: "授权仅覆盖这一会话。正文与来源变化后，原精确批准不再适用。" }
                                    ButtonX { text: "授权本地读取"; primary: true; enabled: window.connected; onClicked: {window.selectedConversation=modelData.conversation_id;window.selectedLabel=modelData.display_name;grantDialog.open()} }
                                    ButtonX { text: "创建近一天任务"; enabled: window.connected && window.permitted(modelData.conversation_id,"messages.read"); onClicked: owner.requestTask(modelData.conversation_id) }
                                }
                            }
                        } }
                        Item { Layout.preferredHeight: 18 }
                    }
                }
                PageScroll {
                    contentHeight: executionPage.implicitHeight
                    ColumnLayout { id: executionPage; width: parent.width; height: implicitHeight; spacing: 12
                        RowLayout { Layout.fillWidth: true; Layout.bottomMargin: 8
                            Badge { text: window.status.audit_valid === true && !window.previewMode ? "安全记录正常" : "安全记录待验证"; symbol: "shield"; ink: Theme.positive }
                            Caption { text: "结果不明的任务不会自动重发。"; Layout.fillWidth: true }
                        }
                        Panel { Layout.fillWidth: true; visible: !window.jobs.length; implicitHeight: 126; Empty { anchors.fill: parent; anchors.margins: 22; heading: "目前没有执行记录"; explanation: "这里会显示实际动作、目标、时间和状态，默认列表不含正文。"; symbol: "activity" } }
                        Repeater { model: window.jobs; delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData } }
                        Item { Layout.preferredHeight: 18 }
                    }
                }
                PageScroll {
                    contentHeight: attachmentPage.implicitHeight
                    ColumnLayout { id: attachmentPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 154
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                RowLayout { Layout.fillWidth: true; Icon { name: "clip"; ink: Theme.positive }
Copy { text: "微信本地文件缓存"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
Item { Layout.fillWidth: true }
Badge { text: (window.backend.attachments || {}).enabled ? "范围已配置" : "尚未配置"; symbol: "lock" } }
                                Caption { Layout.fillWidth: true; text: "按获准消息中的校验值找到实际文件；读取文件与向模型披露分别批准，不下载远程内容。" }
                                ButtonX { text: "设置缓存目录"; primary: true; enabled: window.connected; onClicked: cacheDialog.open() }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 172
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                Copy { text: "第一阶段支持"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Copy { text: "TXT / Markdown     CSV / JSON     Word (.docx)     PDF"; Layout.fillWidth: true; font.weight: Font.Medium }
                                Caption { text: "单文件最多 512 KB，解析文本最多 24 KB。未下载、格式不支持或文件变化会明确报告。"; Layout.fillWidth: true }
                                Caption { text: "图片、语音、视频与扫描版 PDF 暂无内容识别能力，附件中的宏和程序不会执行。"; Layout.fillWidth: true }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 146
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                Copy { text: "专注工作与日常"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "会议信息、文档摘要、任务整理、普通交流与约定确认。\n本阶段不包含支付、转账、朋友圈、小程序、账号设置或群管理。"; lineHeight: 1.6 }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: settingsPage.implicitHeight
                    ColumnLayout { id: settingsPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 106
                            RowLayout { anchors.fill: parent; anchors.margins: 22; spacing: 22
                                ColumnLayout { Layout.fillWidth: true; spacing: 8;Copy { text: "外观"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
Caption { text: "浅色与深色共享相同层级、焦点与状态规则。" } }
                                ButtonX { text: "浅色"; primary: !window.darkMode; onClicked: window.darkMode=false }
                                ButtonX { text: "深色"; primary: window.darkMode; onClicked: window.darkMode=true }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 166
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 16
                                Copy { text: "本地安全与运行"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "权限扩大、正文外发与微信发送保留独立的精确审批和系统身份认证。界面不会自行授予权限。" }
                                RowLayout { ButtonX { text: "查看权限"; onClicked: window.page=3 }
ButtonX { text: "撤销全部授权"; danger: true; enabled: window.connected; onClicked: revokeDialog.open() } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 152
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 12
                                Copy { text: "WeChat MCP Desktop"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { text: "Qt 6 / QML · Powered by Stellaria AXR Gen1" }
                                Caption { Layout.fillWidth: true; text: "开发交付依赖本机运行时。当前 Mac 自动发送尚未通过设备验收；协议连接、合成测试与真实微信能力分别记录。" }
                            }
                        }
                    }
                }
            }
            Rectangle { objectName: "statusBar"; Layout.fillWidth: true; Layout.preferredHeight: 32; color: Theme.canvas
                Rectangle { width: parent.width; height: 1; color: Theme.border }
                RowLayout { anchors.fill: parent; anchors.leftMargin: Theme.margin; anchors.rightMargin: Theme.margin; spacing: 12
                    Caption { text: window.previewMode ? "演示 · 无真实微信" : window.connected ? "本地服务已连接" : "本地服务未连接"; color: window.previewMode ? Theme.warning : Theme.muted }
                    Caption { Layout.fillWidth: true; text: owner.notice; maximumLineCount: 1; elide: Text.ElideRight }
                    Caption { text: "同步 " + (window.backend.last_sync || "—") + "   ·   Gen1"; font.pixelSize: 11 }
                }
            }
        }
    }

    Dialog {
        id: intentDialog; anchors.centerIn: parent; width: Math.min(780,window.width-80); height: 590; modal: true; title: "核对这一次操作"
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { anchors.fill: parent; spacing: 16
            RowLayout { Layout.fillWidth: true; Icon { name: "shield"; ink: Theme.positive }
Copy { text: window.operation(window.intent.operation); font.pixelSize: 20; font.weight: Font.DemiBold } }
            Copy { Layout.fillWidth: true; text: "目标：" + window.targetName((window.intent.resource || {}).conversation_id); font.weight: Font.Medium }
            Caption { Layout.fillWidth: true; text: "目的地：" + window.destinationLabel(window.intent.destination) + "  ·  来源：" + (window.intent.sources || []).length + " 项" }
            Caption { Layout.fillWidth: true; text: "单次批准 · 批准后最长 4 分钟，且不晚于任务截止 " + window.timeLabel((owner.preview || {}).expires) }
            Caption { Layout.fillWidth: true; color: Theme.warning; text: window.intent.operation === "disclosure.send" ? "此操作将精确批准下方内容交给指定模型。请逐项核对。" : "批准绑定当前目标、内容与来源。变更或到期后，需要重新核对。" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { readOnly: true; selectByMouse: true; color: Theme.ink; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; background: Rectangle { color: Theme.canvas; radius: 9 }
                text: (window.intent.payload || {}).text || (window.exactDisclosure.messages || []).map(function(m){return m.text}).join("\n\n") || "此操作不包含可预览正文。技术明细中保留完整密封意图。" } }
            RowLayout { Layout.fillWidth: true; ButtonX { text: "技术明细"; onClicked: technicalDialog.open() }
 Item { Layout.fillWidth: true }
ButtonX { text: "取消"; onClicked: intentDialog.close() }
ButtonX { text: "系统认证并批准"; primary: true; enabled: !window.previewMode && !!(owner.preview || {}).seal; onClicked: owner.approve() } }
        }
    }
    Dialog {
        id: technicalDialog; anchors.centerIn: parent; width: 740; height: 540; modal: true; title: "诊断与技术明细"
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { anchors.fill: parent
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: owner.detail; readOnly: true; color: Theme.ink; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; font.family: Qt.platform.os === "osx" ? "Menlo" : "Consolas"; font.pixelSize: 12; background: Rectangle { color: Theme.canvas } } }
            ButtonX { Layout.alignment: Qt.AlignRight; text: "关闭"; onClicked: technicalDialog.close() }
        }
    }
    Dialog {
        id: draftDialog; anchors.centerIn: parent; width: 740; height: 500; modal: true; title: "回复草稿"
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { anchors.fill: parent; spacing: 14
            Copy { Layout.fillWidth: true; text: (owner.preview || {}).display_name || "读取草稿中…"; font.pixelSize: 18; font.weight: Font.DemiBold }
            Caption { Layout.fillWidth: true; text: "请核对目标、内容与 AI 署名。发送是否可用取决于实际后端和精确授权。" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: (owner.preview || {}).text || ""; readOnly: true; color: Theme.ink; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; background: Rectangle { color: Theme.canvas; radius: 9 } } }
            ButtonX { Layout.alignment: Qt.AlignRight; text: "关闭"; onClicked: draftDialog.close() }
        }
    }
    Dialog {
        id: configDialog; anchors.centerIn: parent; width: 740; height: 480; modal: true; title: "安装 Codex MCP 配置"
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { anchors.fill: parent; spacing: 14
            Caption { Layout.fillWidth: true; text: "只更新 wechat_axr，保留其他设置并建立私有备份。配置安装不会授予微信读取或模型披露权限。" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { text: owner.detail; readOnly: true; color: Theme.ink; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; font.family: Qt.platform.os === "osx" ? "Menlo" : "Consolas"; font.pixelSize: 12; background: Rectangle { color: Theme.canvas } } }
            RowLayout { Layout.alignment: Qt.AlignRight;ButtonX { text: "取消"; onClicked: configDialog.close() }
ButtonX { text: "确认安装"; primary: true; enabled: !window.previewMode; onClicked: {owner.installConfig();configDialog.close()} } }
        }
    }
    Dialog { id: grantDialog; anchors.centerIn: parent; width: 580; modal: true; title: "授权本地访问"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { width: parent.width; spacing: 12
            Copy { Layout.fillWidth: true; text: window.selectedLabel; font.pixelSize: 18; font.weight: Font.DemiBold }
            Caption { Layout.fillWidth: true; text: "当前会话 · 15 分钟 · 最多 100 次读取及草稿操作\n已配置缓存时，包含来源绑定的文件读取。"; lineHeight: 1.6 }
            Caption { Layout.fillWidth: true; color: Theme.warning; text: "不授予模型披露或微信发送。确认后需完成系统身份认证。" }
        }
        onAccepted: owner.grantLocal(window.selectedConversation)
    }
    Dialog { id: cacheDialog; anchors.centerIn: parent; width: 540; modal: true; title: "设置本地缓存范围"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        Caption { width: parent.width; text: "选择微信实际保存附件的目录。系统认证后进入本地文件访问范围，读取仍须来源与会话授权。范围变更会撤销之前的能力。" }
        onAccepted: owner.configureCache()
    }
    Dialog { id: revokeDialog; anchors.centerIn: parent; width: 540; modal: true; title: "撤销全部授权？"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        Caption { width: parent.width; text: "停止监听并撤销当前能力。已披露给外部模型的内容无法收回；重新使用需要再次授权。" }
        onAccepted: owner.stop()
    }
}
