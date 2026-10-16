import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: window
    width: 1280; height: 800; minimumWidth: 1024; minimumHeight: 680
    visible: true; title: "WeChat MCP"
    flags: Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint
    topPadding: 0; bottomPadding: 0; leftPadding: 0; rightPadding: 0
    color: Theme.canvas
    palette.window: Theme.surface; palette.windowText: Theme.ink; palette.text: Theme.ink; palette.base: Theme.surface; palette.button: Theme.surface; palette.buttonText: Theme.ink; palette.highlight: Theme.brand; palette.highlightedText: "white"
    font.family: Qt.platform.os === "osx" ? "PingFang SC" : "Microsoft YaHei UI"
    font.pixelSize: Theme.body
    property int page: 0
    property bool darkMode: false
    property string selectedConversation: ""
    property string selectedLabel: ""
    property var tabs: ["工作台", "Agent 连接", "待办", "权限管理", "执行记录", "附件与内容", "设置", "人工回复", "简报", "待授权"]
    property var glyphs: ["grid", "plug", "inbox", "shield", "activity", "clip", "settings", "message", "brief", "shield"]
    property var backend: owner.data || ({})
    property var status: window.backend.status || ({})
    property var listener: status.listener || ({})
    property var platform: status.platform || ({})
    property bool previewMode: window.backend.scope === "synthetic_preview"
    property bool connected: window.backend.connected === true && !previewMode
    property var autoReply: status.automatic_reply || ({active:false})
    property var autoTargets: []
    property bool autoAll: false
    property var authorizationRequest: ({})
    property string assistantThread: ""
    onPageChanged: { if(page===6)owner.loadAssistant() }
    property int autoMinutes: 15
    property int autoReplies: 4
    property var drafts: window.backend.drafts || []
    property var jobs: window.backend.jobs || []
    property var pending: jobs.filter(function(j){return ["Ready","AwaitingApproval","Executing","Prepared","Verifying"].indexOf(j.state)>=0 && j.expires*1000>Date.now()})
    property var recent: jobs.slice(0,6)
    property var approvals: pending.filter(function(j){return j.state==="AwaitingApproval"})
    property var todos: pending.filter(function(j){return j.state!=="AwaitingApproval"})
    property bool inSettings: [1,3,4,5,6].indexOf(page)>=0
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
    function permitted(cid,op){return (window.autoReply.active && (window.autoReply.targets || []).indexOf(cid)>=0 && ["messages.read","messages.search","reply.prepare"].indexOf(op)>=0) || grantsFor(cid).some(function(g){return g.operations.indexOf(op)>=0 && g.remaining>0})}

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
            ButtonX { visible: !compact && job.state==="Ready"; text: "执行"; enabled: !window.previewMode; onClicked: owner.execute(job.id) }
        }
    }
    component PageScroll: ScrollView { clip: true; contentWidth: availableWidth; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff }
    component WindowDrag: DragHandler {
        target: null
        acceptedButtons: Qt.LeftButton
        onActiveChanged: if (active) window.startSystemMove()
    }

    // Expanded client areas need an explicit non-interactive move surface.
    // Keep native window buttons and page controls outside this region.
    Item {
        objectName: "windowMoveSurface"
        z: 10
        x: Qt.platform.os === "osx" ? 84 : 0
        width: window.width - x - (Qt.platform.os === "windows" ? 150 : 0)
        height: 30
        WindowDrag { }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Item {
            objectName: "sidebar"; Layout.preferredWidth: Theme.sidebarWidth; Layout.fillHeight: true
            Rectangle { objectName: "sidebarCard"; anchors.fill: parent; anchors.margins: 12; radius: 20; color: Theme.glass; border.color: Theme.glassBorder }
            ColumnLayout { anchors.fill: parent; anchors.margins: 26; spacing: 7
                RowLayout { Layout.fillWidth: true; Layout.topMargin: 18; Layout.bottomMargin: 28; spacing: 12
                    WindowDrag { }
                    Rectangle { width: 36; height: 36; radius: 10; color: Theme.brand; Icon { anchors.centerIn: parent; name: "message"; ink: "white"; width: 23; height: 23 } }
                    Column { spacing: 4
                        Copy { text: "WeChat MCP"; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Caption { text: "Desktop"; font.pixelSize: 12 }
                    }
                }
                Repeater { model: [0,8,2,9,7]
                    delegate: Button {
                        id: nav
                        objectName: "nav" + modelData
                        required property int modelData
                        Layout.fillWidth: true; Layout.preferredHeight: 41
                        focusPolicy: Qt.StrongFocus; Accessible.name: window.tabs[modelData]
                        Keys.onReturnPressed: nav.clicked()
                        Keys.onEnterPressed: nav.clicked()
                        background: Rectangle { radius: 9; color: window.page===nav.modelData ? Theme.tint : nav.hovered ? Theme.hover : "transparent"
                            border.color: nav.activeFocus ? Theme.positive : "transparent"; border.width: nav.activeFocus ? 2 : 0 }
                        contentItem: RowLayout { spacing: 11
                            Icon { name: window.glyphs[nav.modelData]; ink: window.page===nav.modelData ? Theme.positive : Theme.muted; width: 19; height: 19; Layout.leftMargin: 12 }
                            Copy { Layout.fillWidth: true; text: window.tabs[nav.modelData]; color: window.page===nav.modelData ? Theme.ink : Theme.muted; font.weight: window.page===nav.modelData ? Font.DemiBold : Font.Normal }
                        }
                        onClicked: window.page=modelData
                    }
                }
                Item { Layout.fillHeight: true }
                ButtonX { objectName: "nav6"; Layout.fillWidth: true; text: "设置"; onClicked: window.page=6
                    background: Rectangle { radius: 9; color: window.inSettings ? Theme.tint : "transparent"; border.color: parent.activeFocus ? Theme.positive : "transparent"; border.width: parent.activeFocus ? 2 : 0 }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                Caption { Layout.topMargin: 16; text: "Powered by"; font.pixelSize: 11 }
                Copy { text: "Stellaria AXR"; font.pixelSize: 16; font.weight: Font.Medium }
                Item { Layout.preferredHeight: 10 }
            }
        }
        ColumnLayout { Layout.fillWidth: true; Layout.fillHeight: true; Layout.topMargin: Qt.platform.os === "windows" ? 30 : 0; spacing: 0
            RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 88; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin
                Column { spacing: 5
                    WindowDrag { }
                    Copy { text: window.tabs[window.page]; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
                    Caption { text: ["今天需要关注的事情", "让助理处理你的消息", "回复与待处理事项", "掌握会话与内容的访问范围", "查看任务进展与结果", "查阅会话中的本地文件", "按你的习惯使用", "由你核对并提交回复", "会话重点与工作摘要", "由你决定哪些操作可以继续"][window.page] }
                }
                Item { Layout.fillWidth: true; Layout.fillHeight: true; WindowDrag { } }
                ButtonX { visible: window.inSettings && window.page!==6; text: "返回设置"; onClicked: window.page=6 }
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
                                    Caption { Layout.fillWidth: true; text: window.previewMode ? "以下仅为界面预览，真实数据与授权操作已停用。" : (window.listener.listen ? "消息监听已请求" : "消息监听已关闭") + " · " + (window.autoReply.active ? "自动回复已开启" : window.autoReply.supported ? "自动回复未开启" : "当前平台暂不支持自动发送") }
                                }
                                ButtonX { text: window.connected ? "连接设置" : "启动本地服务"; primary: true; enabled: !window.previewMode; onClicked: window.connected ? window.page=6 : owner.start() }
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
                                        ButtonX { text: "处理事项"; onClicked: window.page=window.approvals.length ? 9 : window.todos.length ? 2 : 7 }
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
                                Caption { Layout.fillWidth: true; visible: !(window.backend.summaries || []).length; text: "会话摘要会显示在这里。" }
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
Badge { text: window.backend.worker_state === "running" ? "助理正在运行" : "助理未启动"; symbol: "clock" } }
                                Caption { Layout.fillWidth: true; text: "连接 Codex 后，为需要处理的会话授权。" }
                                ButtonX { text: "连接 Codex"; primary: true; enabled: !window.previewMode; onClicked: {owner.configPreview();configDialog.open()} }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 174
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 15
                                Copy { text: "消息助理"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "整理已授权的消息并准备回复。每次运行最长 10 分钟。" }
                                RowLayout { ButtonX { text: "启动助理"; primary: true; enabled: window.connected && window.backend.worker_state !== "running"; onClicked: owner.startAgent() }
ButtonX { text: "查看消息任务"; onClicked: window.page=2 } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: 138
                            ColumnLayout { anchors.fill: parent; anchors.margins: 22; spacing: 13
                                Copy { text: "安装与恢复"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Caption { Layout.fillWidth: true; text: "连接前会备份 Codex 设置，可恢复本次连接前的状态。" }
                                ButtonX { text: "恢复原设置"; enabled: !window.previewMode && owner.restoreAvailable; onClicked: owner.restoreConfig() }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: messagePage.implicitHeight
                    ColumnLayout { id: messagePage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: 80
                            RowLayout { anchors.fill: parent; anchors.margins: 22; Icon { name: "message"; ink: Theme.positive }
                                Copy { Layout.fillWidth: true; text: window.autoReply.active ? "自动回复已开启" : window.autoReply.supported ? "可在设置中授权自动回复" : "自动发送暂不可用"; font.weight: Font.Medium }
                                ButtonX { text: "人工回复"; onClicked: window.page=7 }
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
                                            Caption { text: "有效至 " + window.timeLabel(modelData.expires) }
                                        }
                                        ButtonX { text: "人工处理"; enabled: !window.previewMode; onClicked: {window.page=7;owner.manualDraft(modelData.job_id)} }
                                    }
                                } }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: taskContent.implicitHeight+44
                            ColumnLayout { id: taskContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 22; spacing: 14
                                Copy { text: "正在处理"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Empty { Layout.fillWidth: true; visible: !window.todos.length; heading: "暂无待办"; explanation: "需要你处理的任务会显示在这里。"; symbol: "shield" }
                                Repeater { model: window.todos; delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData } }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: permissionPage.implicitHeight
                    ColumnLayout { id: permissionPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        RowLayout { Layout.fillWidth: true; spacing: 20
                            Badge { text: "会话授权"; symbol: "shield"; ink: Theme.positive }
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
Copy { text: window.permitted(modelData.conversation_id,"messages.read") ? "已允许读取" : "未授权" } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6; Caption { text: "发送给模型分析" }
Copy { text: window.permitted(modelData.conversation_id,"disclosure.send") ? "本次已批准" : "使用前确认" } }
                                    ColumnLayout { Layout.fillWidth: true; spacing: 6; Caption { text: "自动发送消息" }
Copy { text: window.autoReply.active ? "已按所选范围授权" : window.autoReply.supported ? "尚未授权" : "当前平台暂不支持"; color: Theme.muted } }
                                }
                                Repeater { model: grants; delegate: Caption { required property var modelData; Layout.fillWidth: true
                                    text: "截止 " + window.timeLabel(modelData.expires) + " · 剩余 " + modelData.remaining + " 次 · " + (modelData.exact_intent ? "仅本次操作" : "本机访问") + " · 使用方：" + (modelData.destinations.length ? modelData.destinations.map(window.destinationLabel).join("、") : "仅本机")
                                } }
                                RowLayout { Layout.fillWidth: true
                                    Caption { Layout.fillWidth: true; text: "授权仅覆盖这一会话。正文与来源变化后，原精确批准不再适用。" }
                                    ButtonX { text: "授权本地读取"; primary: true; enabled: window.connected; onClicked: {window.selectedConversation=modelData.conversation_id;window.selectedLabel=modelData.display_name;grantDialog.open()} }
                                    ButtonX { text: "整理最近消息"; enabled: window.connected && window.permitted(modelData.conversation_id,"messages.read"); onClicked: owner.requestTask(modelData.conversation_id) }
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
                                Copy { text: "支持的文件"; font.pixelSize: Theme.section; font.weight: Font.DemiBold }
                                Copy { text: "TXT / Markdown     CSV / JSON     Word (.docx)     PDF"; Layout.fillWidth: true; font.weight: Font.Medium }
                                Caption { text: "单文件最多 512 KB，解析文本最多 24 KB。未下载、格式不支持或文件变化会明确报告。"; Layout.fillWidth: true }
                                Caption { text: "图片、语音、视频与扫描版 PDF 暂无内容识别能力，附件中的宏和程序不会执行。"; Layout.fillWidth: true }
                            }
                        }
                    }
                }
                PageScroll {
                    contentHeight: settingsPage.implicitHeight
                    ColumnLayout { id: settingsPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Panel { Layout.fillWidth: true; implicitHeight: autoRows.implicitHeight+40
                            ColumnLayout { id: autoRows; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 14
                                Copy { text: "自动回复"; font.pixelSize: 18; font.weight: Font.Medium }
                                Caption { Layout.fillWidth: true; visible: !!(window.status.security || {}).automatic_block; text: "自动回复已暂停。完成安全服务升级后，再为指定对象开启授权。" }
                                Caption { Layout.fillWidth: true; text: window.autoReply.active ? "已开启 · " + (window.autoReply.expires ? "有效至 " + window.timeLabel(window.autoReply.expires) : "不限时长，直至停止") + " · 剩余 " + (window.autoReply.remaining===null ? "不限" : window.autoReply.remaining) + " 次" : "允许 Codex 阅读范围内的新消息、生成回复并发送。发送时微信会置前。" }
                                Caption { Layout.fillWidth: true; visible: window.autoReply.active; text: "范围：已授权 " + (window.autoReply.targets || []).length + " 个私聊，可在权限管理查看。" }
                                CheckBox { visible: !window.autoReply.active; text: "全部可用私聊（含后续核验的新会话）"; checked: window.autoAll; enabled: !window.autoReply.active; onToggled: window.autoAll=checked }
                                TextField { id: targetSearch; visible: !window.autoAll && !window.autoReply.active; Layout.fillWidth: true; placeholderText: "搜索授权对象"; enabled: !window.autoReply.active }
                                Flow { Layout.fillWidth: true; spacing: 8; visible: !window.autoAll
                                    Repeater { model: (window.backend.conversations || []).filter(function(c){return c.display_name.indexOf(targetSearch.text)>=0}).slice(0,40)
                                        CheckBox { text: modelData.display_name; enabled: !window.autoReply.active && !window.previewMode
                                            checked: window.autoTargets.indexOf(modelData.conversation_id)>=0
                                            Accessible.name: "自动回复范围：" + text
                                            onToggled: { var ids=window.autoTargets.slice(); var at=ids.indexOf(modelData.conversation_id); if(checked && at<0)ids.push(modelData.conversation_id); if(!checked && at>=0)ids.splice(at,1); window.autoTargets=ids }
                                        }
                                    }
                                }
                                RowLayout { Layout.fillWidth: true; spacing: 12
                                    Caption { visible: !window.autoReply.active; text: "有效时长" }
                                    ComboBox { objectName: "autoDuration"; visible: !window.autoReply.active; model: ["5 分钟", "15 分钟", "30 分钟", "60 分钟", "不限时长"]; currentIndex: 1; enabled: !window.autoReply.active; onActivated: window.autoMinutes=[5,15,30,60,0][currentIndex]; Accessible.name: "自动回复有效时长" }
                                    Caption { visible: !window.autoReply.active; text: "最多回复" }
                                    SpinBox { objectName: "autoReplyLimit"; visible: !window.autoReply.active; from: 0; to: 1000000; value: 4; textFromValue: function(value,locale){return value===0 ? "不限" : value.toString()}; enabled: !window.autoReply.active; onValueModified: window.autoReplies=value; Accessible.name: "最多自动回复次数" }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { objectName: "autoStart"; text: "授权并开启"; primary: true; enabled: window.connected && window.autoReply.supported === true && !window.autoReply.active && (window.autoAll || window.autoTargets.length>=2) && Qt.platform.os === "osx"; onClicked: autoDialog.open() }
                                    ButtonX { objectName: "autoStop"; text: "停止自动回复"; danger: true; enabled: window.connected && (window.autoReply.active || window.backend.automatic_pending === true || (window.backend.automatic_worker || {}).running === true); onClicked: owner.stopAutomatic() }
                                }
                                Caption { Layout.fillWidth: true; text: "仅回复开启后的入站文字。次数填 0 表示不限；不确定的发送不会重发。Codex 忙时只排队索引，正文按需重读。停止、到期或退出服务后撤权。" }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: assistantRows.implicitHeight+40
                            ColumnLayout { id: assistantRows; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 12
                                Copy { text: "你的 Codex 助理"; font.pixelSize: 18; font.weight: Font.Medium }
                                Caption { Layout.fillWidth: true; text: "所有触发留在同一个 Codex 对话。正在执行用户任务时排队，结束后再处理。" }
                                RowLayout { Layout.fillWidth: true
                                    ComboBox { id: threadChoice; enabled: !window.autoReply.active; Layout.fillWidth: true; model: owner.codexThreads; textRole: "title"; valueRole: "id"; Accessible.name: "绑定的 Codex 对话"; onActivated: window.assistantThread=currentValue }
                                    ButtonX { text: "选择对话"; enabled: window.connected && !window.autoReply.active; onClicked: owner.loadThreads() }
                                    ButtonX { text: "更多对话"; enabled: window.connected && !window.autoReply.active; onClicked: owner.loadMoreThreads() }
                                }
                                Caption { Layout.fillWidth: true; text: "已绑定：" + ((owner.assistant || {}).thread_title || "未选择") + " · " + ((window.backend.thread_binding || {}).state==="busy" ? "当前任务进行中，微信任务排队" : (window.backend.thread_binding || {}).hooks_observed ? "已连接生命周期" : "等待 Codex 连接事件") }
                                RowLayout { Layout.fillWidth: true
                                    ButtonX { text: "配置对话连接"; enabled: window.connected && !window.autoReply.active; onClicked: owner.installHooks() }
                                    Caption { Layout.fillWidth: true; text: "首次配置后在 Codex 的 /hooks 审核。不会模拟快捷键或改写输入框。" }
                                }
                                Caption { text: "人设" }
                                ScrollView { Layout.fillWidth: true; Layout.preferredHeight: 110
                                    TextArea { id: personaInput; text: (owner.assistant || {}).persona || ""; placeholderText: "助理的身份、沟通偏好与工作背景"; wrapMode: TextEdit.Wrap; color: Theme.ink; background: Rectangle { color: Theme.canvas; radius: 9 } }
                                }
                                Caption { text: "回复风格" }
                                TextField { id: styleInput; Layout.fillWidth: true; text: (owner.assistant || {}).style || ""; placeholderText: "例如：自然简短，先回答问题，再列待办" }
                                CheckBox { id: attributionChoice; text: "在回复中显示 AI 署名"; checked: (owner.assistant || {}).attribution !== false }
                                RowLayout { Layout.fillWidth: true
                                    ButtonX { text: "导入人设"; enabled: !window.autoReply.active; onClicked: owner.importPersona() }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "保存助理偏好"; primary: true; enabled: window.connected && !window.autoReply.active; onClicked: owner.saveAssistant({thread_id:window.assistantThread || (owner.assistant || {}).thread_id || "",thread_title:window.assistantThread ? threadChoice.currentText : (owner.assistant || {}).thread_title || "",persona:personaInput.text,style:styleInput.text,attribution:attributionChoice.checked}) }
                                }
                            }
                        }
                        Panel { Layout.fillWidth: true; visible: (window.backend.authorization_requests || []).some(function(r){return r.state==="AwaitingOwner"}); implicitHeight: requestRows.implicitHeight+40
                            ColumnLayout { id: requestRows; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 12
                                Copy { text: "待授权请求"; font.pixelSize: 18; font.weight: Font.Medium }
                                Repeater { model: (window.backend.authorization_requests || []).filter(function(r){return r.state==="AwaitingOwner"})
                                    RowLayout { required property var modelData; Layout.fillWidth: true
                                        ColumnLayout { Layout.fillWidth: true; Copy { text: modelData.target } Caption { Layout.fillWidth: true; text: modelData.reason } }
                                        ButtonX { text: "查看并授权"; onClicked: {window.authorizationRequest=modelData;authorizationDialog.open()} }
                                    }
                                }
                            }
                        }
                        Panel { Layout.fillWidth: true; implicitHeight: settingRows.implicitHeight+40
                            ColumnLayout { id: settingRows; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 20
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.preferredWidth: 280; Layout.minimumWidth: 200; Layout.maximumWidth: 280; spacing: 5
                                        Copy { text: "外观"; font.weight: Font.Medium }
                                        Caption { text: "选择你喜欢的主题" }
                                    }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "浅色"; primary: !window.darkMode; onClicked: window.darkMode=false }
                                    ButtonX { text: "深色"; primary: window.darkMode; onClicked: window.darkMode=true }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.preferredWidth: 280; Layout.minimumWidth: 200; Layout.maximumWidth: 280; spacing: 5
                                        Copy { text: "连接"; font.weight: Font.Medium }
                                        Caption { text: "管理 Codex 与消息助理" }
                                    }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "连接管理"; onClicked: window.page=1 }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.preferredWidth: 280; Layout.minimumWidth: 200; Layout.maximumWidth: 280; spacing: 5
                                        Copy { text: "隐私与权限"; font.weight: Font.Medium }
                                        Caption { Layout.fillWidth: true; text: "随时查看或撤销会话授权" }
                                    }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "管理权限"; onClicked: window.page=3 }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.preferredWidth: 280; Layout.minimumWidth: 200; Layout.maximumWidth: 280; spacing: 5
                                        Copy { text: "文件与记录"; font.weight: Font.Medium }
                                        Caption { text: "管理本地文件目录，查看处理历史" }
                                    }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "附件目录"; onClicked: window.page=5 }
                                    ButtonX { text: "执行记录"; onClicked: window.page=4 }
                                }
                                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                                RowLayout { Layout.fillWidth: true; spacing: 16
                                    ColumnLayout { Layout.preferredWidth: 280; Layout.minimumWidth: 200; Layout.maximumWidth: 280; spacing: 5
                                        Copy { text: "暂停访问"; font.weight: Font.Medium }
                                        Caption { Layout.fillWidth: true; text: "停止监听并撤销当前授权" }
                                    }
                                    Item { Layout.fillWidth: true }
                                    ButtonX { text: "撤销授权"; danger: true; enabled: window.connected; onClicked: revokeDialog.open() }
                                }
                            }
                        }
                        RowLayout { Layout.fillWidth: true; Layout.topMargin: 8
                            Caption { text: "WeChat MCP Desktop" }
                            Item { Layout.fillWidth: true }
                            Caption { text: "Stellaria AXR · Gen1" }
                        }

                    }
                }
                PageScroll {
                    objectName: "manualRepliesPage"; contentHeight: manualPage.implicitHeight
                    ColumnLayout { id: manualPage; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        Caption { Layout.fillWidth: true; text: "选择草稿，核对收件人与内容，然后到微信提交。" }
                        Empty { visible: !window.drafts.length; Layout.fillWidth: true; heading: "暂无待回复消息"; explanation: "助理准备好的回复会显示在这里。"; symbol: "message" }
                        RowLayout { visible: window.drafts.length>0; Layout.fillWidth: true; spacing: 20; Layout.alignment: Qt.AlignTop
                            ColumnLayout { Layout.preferredWidth: 224; Layout.minimumWidth: 224; Layout.maximumWidth: 224; Layout.alignment: Qt.AlignTop; spacing: 8
                                Repeater { model: window.drafts; delegate: ButtonX {
                                    required property var modelData; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.maximumWidth: 224
                                    text: modelData.display_name; primary: (owner.manual || {}).job_id===modelData.job_id
                                    enabled: !window.previewMode; onClicked: owner.manualDraft(modelData.job_id)
                                } }
                            }
                            Panel { Layout.fillWidth: true; Layout.minimumWidth: 320; Layout.alignment: Qt.AlignTop; implicitHeight: manualContent.implicitHeight+40
                                ColumnLayout { id: manualContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 16
                                    Empty { visible: !(owner.manual || {}).job_id; Layout.fillWidth: true; heading: "选择一份回复草稿"; explanation: "发送前请确认目标与内容。"; symbol: "message" }
                                    Copy { visible: !!(owner.manual || {}).job_id; Layout.fillWidth: true; text: (owner.manual || {}).display_name || ""; font.pixelSize: 18; font.weight: Font.DemiBold }
                                    Caption { visible: !!(owner.manual || {}).job_id; Layout.fillWidth: true; text: "有效至 " + window.timeLabel((owner.manual || {}).expires) }
                                    ScrollView { visible: !!(owner.manual || {}).job_id; Layout.fillWidth: true; Layout.preferredHeight: 280
                                        TextArea { objectName: "manualDraftText"; text: (owner.manual || {}).text || ""; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; color: Theme.ink; wrapMode: TextEdit.Wrap; background: Rectangle { color: Theme.canvas; radius: 9 } }
                                    }
                                    RowLayout { visible: !!(owner.manual || {}).job_id; Layout.fillWidth: true
                                        ButtonX { objectName: "manualCopy"; text: "复制回复"; primary: true; enabled: !window.previewMode; onClicked: owner.copyDraft() }
                                        Item { Layout.fillWidth: true }
                                        ButtonX { text: "核对已发送记录"; enabled: !window.previewMode; onClicked: owner.observeManual() }
                                    }
                                }
                            }
                        }
                    }
                }

                PageScroll {
                    objectName: "briefPage"; contentHeight: briefContent.implicitHeight
                    ColumnLayout { id: briefContent; width: parent.width; height: implicitHeight; spacing: Theme.gap
                        RowLayout { Layout.fillWidth: true
                            Caption { Layout.fillWidth: true; text: "仅显示已授权且仍有效的摘要。" }
                            ButtonX { text: "更新简报"; enabled: window.connected; onClicked: owner.summaries() }
                        }
                        Empty { Layout.fillWidth: true; visible: !(window.backend.summaries || []).length; heading: "暂无简报"; explanation: "会话重点、待确认事项与工作建议会显示在这里。"; symbol: "brief" }
                        Repeater { model: window.backend.summaries || []; delegate: Panel {
                            required property var modelData; Layout.fillWidth: true; implicitHeight: briefRow.implicitHeight+40
                            ColumnLayout { id: briefRow; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 12
                                Copy { Layout.fillWidth: true; text: modelData.summary }
                                Caption { text: "根据 " + modelData.text_records + " 条消息整理" }
                            }
                        } }
                    }
                }
                PageScroll {
                    objectName: "approvalPage"; contentHeight: approvalContent.implicitHeight
                    ColumnLayout { id: approvalContent; width: parent.width; height: implicitHeight; spacing: 12
                        Empty { Layout.fillWidth: true; visible: !window.approvals.length && !(window.backend.authorization_requests || []).some(function(r){return r.state==="AwaitingOwner"}); heading: "暂无待授权操作"; explanation: "需要你批准的内容访问或回复会单独显示。"; symbol: "shield" }
                        Repeater { model: (window.backend.authorization_requests || []).filter(function(r){return r.state==="AwaitingOwner"})
                            Panel { required property var modelData; Layout.fillWidth: true; implicitHeight: 100
                                RowLayout { anchors.fill: parent; anchors.margins: 20
                                    ColumnLayout { Layout.fillWidth: true; Copy { text: modelData.target; font.weight: Font.Medium } Caption { Layout.fillWidth: true; text: modelData.reason } }
                                    ButtonX { text: "查看并授权"; onClicked: {window.authorizationRequest=modelData;authorizationDialog.open()} }
                                }
                            }
                        }
                        Repeater { model: window.approvals; delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData } }
                    }
                }

            }
            Rectangle { objectName: "statusBar"; Layout.fillWidth: true; Layout.preferredHeight: 32; color: Theme.canvas
                Rectangle { width: parent.width; height: 1; color: Theme.border }
                RowLayout { anchors.fill: parent; anchors.leftMargin: Theme.margin; anchors.rightMargin: Theme.margin; spacing: 12
                    Caption { text: window.previewMode ? "演示 · 无真实微信" : window.connected ? "本地服务已连接" : "本地服务未连接"; color: window.previewMode ? Theme.warning : Theme.muted }
                    Caption { Layout.fillWidth: true; text: owner.notice; maximumLineCount: 1; elide: Text.ElideRight }
                    Caption { text: "同步 " + (window.backend.last_sync || "—"); font.pixelSize: 11 }
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
            Caption { Layout.fillWidth: true; visible: !!((window.intent.payload || {}).relative_path || (window.intent.payload || {}).path || (window.intent.payload || {}).filename)
                text: "文件：" + ((window.intent.payload || {}).relative_path || (window.intent.payload || {}).path || (window.intent.payload || {}).filename || "") }
            Caption { Layout.fillWidth: true; visible: (window.intent.payload || {}).limit !== undefined
                text: "读取范围：" + ((window.intent.payload || {}).since ? window.timeLabel(window.intent.payload.since) : "最早记录") + " 至 " + ((window.intent.payload || {}).until>253402300799 ? "不限" : window.timeLabel((window.intent.payload || {}).until)) + " · 最多 " + (window.intent.payload || {}).limit + " 条" }
            Caption { Layout.fillWidth: true; text: "目的地：" + window.destinationLabel(window.intent.destination) + "  ·  来源：" + (window.intent.sources || []).length + " 项" }
            Caption { Layout.fillWidth: true; text: "单次批准 · 批准后最长 4 分钟，且不晚于任务截止 " + window.timeLabel((owner.preview || {}).expires) }
            Caption { Layout.fillWidth: true; color: Theme.warning; text: window.intent.operation === "disclosure.send" ? "此操作将精确批准下方内容交给指定模型。请逐项核对。" : "批准绑定当前目标、内容与来源。变更或到期后，需要重新核对。" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { readOnly: true; selectByMouse: true; color: Theme.ink; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; background: Rectangle { color: Theme.canvas; radius: 9 }
                text: (window.intent.payload || {}).text || (window.intent.payload || {}).content || (window.exactDisclosure.messages || []).map(function(m){return m.text}).join("\n\n") || "此操作没有消息正文。请核对上方目标与范围。" } }
            RowLayout { Layout.fillWidth: true;
 Item { Layout.fillWidth: true }
ButtonX { text: "取消"; onClicked: intentDialog.close() }
ButtonX { text: "系统认证并批准"; primary: true; enabled: !window.previewMode && !!(owner.preview || {}).seal; onClicked: owner.approve() } }
        }
    }
    Dialog {
        id: configDialog; anchors.centerIn: parent; width: 540; modal: true; title: "连接 Codex"
        background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.border }
        ColumnLayout { width: parent.width; spacing: 20
            Copy { Layout.fillWidth: true; text: "为 Codex 添加微信连接"; font.pixelSize: 18; font.weight: Font.DemiBold }
            Caption { Layout.fillWidth: true; text: "将添加或更新微信连接，并备份当前设置。其他连接会保留。" }
            Caption { Layout.fillWidth: true; text: "连接后，读取会话和将内容交给助理仍需由你授权。" }
            RowLayout { Layout.alignment: Qt.AlignRight
                ButtonX { text: "取消"; onClicked: configDialog.close() }
                ButtonX { text: "连接"; primary: true; enabled: !window.previewMode; onClicked: {owner.installConfig();configDialog.close()} }
            }
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
    Dialog { id: authorizationDialog; anchors.centerIn: parent; width: Math.min(520,window.width-60); modal: true; title: "授权指定联系人"; standardButtons: Dialog.Cancel | Dialog.Ok
        contentItem: Copy { text: "目标：" + (window.authorizationRequest.target || "") + "\n用途：" + (window.authorizationRequest.reason || "") + "\n\n允许本地读取与草稿；自动回复会话运行时，将该目标加入当前回复范围并允许向 Codex 披露及回复。将通过本机系统认证和唯一身份核对，聊天消息不能自行授予权限。" }
        onAccepted: owner.approveAuthorization(window.authorizationRequest.id)
    }
    Dialog { id: autoDialog; anchors.centerIn: parent; width: Math.min(560,window.width-60); modal: true; title: "确认自动回复授权"; standardButtons: Dialog.Cancel | Dialog.Ok
        contentItem: Copy { text: "目标：" + (window.autoAll ? "当前账号全部可用私聊及后续新核验的私聊；排除群、公众号、系统会话" : window.autoTargets.map(window.targetName).join("、")) + "\n时长：" + (window.autoMinutes ? window.autoMinutes + " 分钟" : "不限时长，直到停止") + "，回复：" + (window.autoReplies ? "最多 " + window.autoReplies + " 次" : "不限次数") + "。\n\n允许把所选私聊的新消息发给 Codex 生成回复，再自动发送到原私聊。发送时微信会置前；请勿同时操作输入区。已有草稿或身份核对失败会停止。\n\n接下来需要本机系统身份认证，单次原生提交凭据保持短期；不限会话只在当前服务中续发，停止立即撤权。" }
        onAccepted: owner.startAutomatic(window.autoAll ? ["*"] : window.autoTargets,window.autoMinutes,window.autoReplies)
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
