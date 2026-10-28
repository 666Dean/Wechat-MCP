import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
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
    property bool independentService: window.status.authority === "independent-native-v2"
    property var autoReply: status.automatic_reply || ({active:false})
    property bool scopeActive: status.owner_authorized === true || autoReply.active === true
    property int accessLevel: scopeActive ? ((status.scope || {}).self_agent===true ? 2 : autoReply.active ? 1 : 0) : 0
    function allowance(value){return value===null || value===undefined || !isFinite(value) ? "不限次数" : "剩余 " + value + " 次"}
    function openAccess(level){
        accessEditor.level=level;accessEditor.contacts=backend.conversations || [];
        accessEditor.authorizedIds=(backend.grants || []).map(function(g){return g.conversation_id});
        accessEditor.selectedIds=accessEditor.authorizedIds.filter(function(id){return accessEditor.contacts.some(function(c){return c.conversation_id===id})});accessEditor.overwriteDrafts=(status.scope || {}).overwrite_drafts===true;
        accessEditor.allContacts=scopeActive && accessEditor.authorizedIds.length===accessEditor.contacts.length && accessEditor.contacts.length>0;
        accessEditor.activeScope=scopeActive;accessEditor.minutes=scopeActive && !autoReply.expires ? 0 : 30;
        accessEditor.replies=scopeActive && (autoReply.remaining===null || autoReply.remaining===undefined) ? 0 : 20;
        accessEditor.bindingReady=!!(owner.assistant || {}).thread_id;
        accessEditor.sendPolicy=(status.scope || {}).send_policy || "immediate";
        accessEditor.backgroundAvailable=status.background_send_qualified===true;
        if(accessEditor.sendPolicy==="background_when_idle" && !accessEditor.backgroundAvailable)accessEditor.sendPolicy="when_idle";
        if(level===2)Qt.callLater(function(){riskDialog.open()});else Qt.callLater(function(){accessEditor.open()})
    }
    property bool systemReady: !status.permissions || (status.permissions.database === true && status.permissions.accessibility === true)
    property var autoTargets: []
    property bool autoAll: false
    property var authorizationRequest: ({})
    property var assistantDraft: ({})
    onPageChanged: { if(page===6)owner.loadAssistant() }
    Component.onCompleted: if(owner.onboardingNeeded)Qt.callLater(function(){setupDialog.open()})
    property int autoMinutes: 15
    property int autoReplies: 4
    property bool overwriteDrafts: false
    property bool selfAgentAccess: false
    function requestRevoke(){revokeDialog.open()}
    Connections { target: owner; function onAgentApprovalChanged(){if((owner.agentApproval || {}).request_key)agentActionDialog.open();else agentActionDialog.close()} }
    property var drafts: window.backend.drafts || []
    property var jobs: window.backend.jobs || []
    property var pending: jobs.filter(function(j){return ["Ready","Queued","WaitingForIdle","AwaitingApproval","AwaitingDisclosureApproval","AwaitingInference","DisclosureReady","Executing","Prepared","Verifying","AwaitingAgent","HandedOff"].indexOf(j.state)>=0 && j.expires*1000>Date.now()})
    property var recent: jobs.slice().sort(function(a,b){return b.created-a.created}).slice(0,6)
    property var approvals: pending.filter(function(j){return j.state==="AwaitingApproval" || j.state==="AwaitingDisclosureApproval"})
    property var todos: pending.filter(function(j){return j.state!=="AwaitingApproval" && j.state!=="AwaitingDisclosureApproval"})
    property bool inSettings: [1,3,4,5,6].indexOf(page)>=0
    property var intent: (owner.preview || {}).intent || ({})
    property var exactDisclosure: (owner.preview || {}).exact_disclosure || ({})
    property bool sendAvailable: !previewMode && platform.send_available === true
    Binding { target: Theme; property: "motionEnabled"; value: !owner.reduceMotion }
    Binding { target: Theme; property: "dark"; value: window.darkMode }
    Binding { target: Theme; property: "glassSource"; value: appContent }
    function operation(op){return ({"owner.command":"本人任务","messages.read":"读取消息","messages.search":"搜索消息","files.read":"解析本地附件","reply.prepare":"生成回复草稿","disclosure.send":"内容披露审批","messages.send":"提交微信回复","workspace.write":"保存工作文档","application.navigate":"应用导航","expired":"已过期任务"})[op] || "处理任务"}
    function stateLabel(state){return ({"WaitingForIdle":"等待电脑空闲后发送","AwaitingAgent":"等待 Codex 当前任务结束","HandedOff":"Codex 正在处理本人任务","AwaitingApproval":"等待你的批准","AwaitingDisclosureApproval":"等待披露内容审批","AwaitingInference":"等待生成回复","DisclosureReady":"已批准，等待原请求方读取","Ready":"等待执行","Queued":"等待处理","Draft":"等待人工回复","Observed":"已核对本机发出记录","Executing":"正在处理","Prepared":"已准备","Verifying":"核验结果","Completed":"已完成","Unknown":"结果待核对","FailedSafe":"已安全停止","Expired":"已过期","Cancelled":"已取消","Denied":"已拒绝","Proposed":"待检查","PolicyChecked":"已检查权限"})[state] || "待验证"}
    function destinationLabel(value){return value === "local" ? "仅本机" : value === "model:codex" ? "Codex" : value && value.indexOf("wechat:")===0 ? "指定微信会话" : value && value.indexOf("model:")===0 ? "模型：" + value.slice(6) : value || "—"}
    function targetName(cid){var list=window.backend.conversations || [];for(var i=0;i<list.length;i++)if(list[i].conversation_id===cid)return list[i].display_name;return cid || "本地操作"}
    function timeLabel(value){return value ? new Date(value*1000).toLocaleString(Qt.locale(),"MM-dd HH:mm") : "—"}
    function grantsFor(cid){return (window.backend.grants || []).filter(function(g){return g.conversation_id===cid})}
    function permitted(cid,op){return (window.autoReply.active && (window.autoReply.targets || []).indexOf(cid)>=0 && ["messages.read","messages.search","reply.prepare"].indexOf(op)>=0) || grantsFor(cid).some(function(g){return g.operations.indexOf(op)>=0 && (g.remaining===null || g.remaining>0)})}

    component Copy: Text { color: Theme.ink; textFormat: Text.PlainText; wrapMode: Text.WordWrap; font.pixelSize: Theme.body }
    component Caption: Copy { color: Theme.muted; font.pixelSize: Theme.caption }
    component Field: TextField {
        id: field
        implicitHeight: 40; leftPadding: 12; rightPadding: 12; color: Theme.ink
        placeholderTextColor: Theme.muted; selectByMouse: true
        background: Rectangle { radius: 11; color: Theme.canvas; border.width: field.activeFocus ? 2 : 1; border.color: field.activeFocus ? Theme.positive : Theme.border }
    }
    component CheckX: CheckBox {
        id: check; implicitHeight: 36; spacing: 10
        indicator: Rectangle { x: check.leftPadding; y: (check.height-height)/2; width: 20; height: 20; radius: 6
            color: check.checked ? Theme.brand : Theme.surface; border.color: check.activeFocus ? Theme.positive : check.checked ? Theme.brand : Theme.border
            border.width: check.activeFocus ? 2 : 1
            Icon { anchors.centerIn: parent; width: 15; height: 15; name: "tick"; ink: "white"; visible: check.checked }
        }
        contentItem: Text { text: check.text; font: check.font; color: check.enabled ? Theme.ink : Theme.muted
            leftPadding: check.indicator.width+check.spacing; verticalAlignment: Text.AlignVCenter; textFormat: Text.PlainText
        }
    }
    component ButtonX: Button {
        id: control
        scale: down ? .98 : 1
        Behavior on scale { NumberAnimation { duration: Theme.motionEnabled ? 100 : 0 } }
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
    component Panel: Rectangle { color: Theme.surface; radius: Theme.radius; border.color: Theme.border; border.width: 1 }
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
            ButtonX { visible: !compact; objectName: "pendingReview_" + job.id
                property bool exactPending: window.status.pending_review_supported===true && (job.state==="AwaitingApproval" || job.state==="AwaitingDisclosureApproval")
                text: exactPending ? "核对并批准" : "核对详情"; enabled: !exactPending || !window.previewMode
                onClicked: {if(exactPending)owner.approvePending(job.id);else {owner.review(job.id);intentDialog.open()}} }
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
        id: appContent
        anchors.fill: parent; spacing: 0
        Item {
            objectName: "sidebar"; Layout.preferredWidth: Theme.sidebarWidth; Layout.fillHeight: true
            Rectangle { objectName: "sidebarCard"; anchors.fill: parent; anchors.margins: 12; radius: 20; color: Theme.glass; border.color: Theme.glassBorder }
            ColumnLayout { anchors.fill: parent; anchors.margins: 26; spacing: 7
                RowLayout { Layout.fillWidth: true; Layout.topMargin: 18; Layout.bottomMargin: 28; spacing: 12
                    WindowDrag { }
                    Image { source: "icon.svg"; Layout.preferredWidth: 40; Layout.preferredHeight: 40; sourceSize.width: 160; sourceSize.height: 160 }
                    Column { spacing: 4
                        Copy { text: "WeChat MCP"; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Caption { text: "Desktop"; font.pixelSize: 12 }
                    }
                }
                Caption { text: "对话"; Layout.leftMargin: 12; Layout.bottomMargin: 4 }
                Repeater { model: [0,7]
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
                Caption { text: "项目"; Layout.leftMargin: 12; Layout.topMargin: 22; Layout.bottomMargin: 4 }
                Repeater { model: [8,2,9]
                    Button { id: projectNav; required property int modelData; objectName: "nav"+modelData; Layout.fillWidth: true; Layout.preferredHeight: 41; focusPolicy: Qt.StrongFocus; Accessible.name: window.tabs[modelData]
                        Keys.onReturnPressed: projectNav.clicked(); Keys.onEnterPressed: projectNav.clicked()
                        background: Rectangle { radius: 9; color: window.page===projectNav.modelData ? Theme.tint : projectNav.hovered ? Theme.hover : "transparent"; border.color: projectNav.activeFocus ? Theme.positive : "transparent"; border.width: projectNav.activeFocus ? 2 : 0
                        }
                        contentItem: RowLayout { spacing: 11
                            Icon { name: window.glyphs[projectNav.modelData]; ink: window.page===projectNav.modelData ? Theme.positive : Theme.muted; width: 19; height: 19; Layout.leftMargin: 12 }
                            Copy { Layout.fillWidth: true; text: window.tabs[projectNav.modelData]; color: window.page===projectNav.modelData ? Theme.ink : Theme.muted; font.weight: window.page===projectNav.modelData ? Font.DemiBold : Font.Normal }
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
                ColumnLayout { Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                    WindowDrag { }
                    Copy { Layout.fillWidth: true; maximumLineCount: 1; elide: Text.ElideRight; text: window.page===0 ? ((owner.assistant || {}).thread_title || "你的助理") : window.tabs[window.page]; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
                    Caption { visible: window.page!==0; text: ["在桌面与微信之间继续任务", "让助理处理你的消息", "回复与待处理事项", "掌握会话与内容的访问范围", "查看任务进展与结果", "查阅会话中的本地文件", "按你的习惯使用", "由你核对并提交回复", "会话重点与工作摘要", "由你决定哪些操作可以继续"][window.page] }
                }
                Item { Layout.preferredWidth: 12; Layout.fillHeight: true; WindowDrag { } }
                ButtonX { visible: window.inSettings && window.page!==6; text: "返回设置"; onClicked: window.page=6 }
                BusyIndicator { running: window.backend.loading === true; visible: running; implicitWidth: 22; implicitHeight: 22 }
                Badge { objectName: "connectionStatus"; text: window.previewMode ? "演示 · 无真实微信" : window.scopeActive ? "微信访问已授权" : window.connected ? "服务已连接 · 待授权" : "服务未连接"; symbol: window.scopeActive ? "shield" : "plug"; ink: window.scopeActive ? Theme.positive : Theme.muted }
                ButtonX { visible: window.page!==0; text: "刷新"; enabled: window.backend.loading !== true; onClicked: owner.refresh() }
            }
            Rectangle { Layout.fillWidth: true; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin
                visible: owner.notice!=="已同步。" && owner.notice!=="操作已完成。" && owner.notice!=="连接本地服务，开始你的工作台。"; Layout.preferredHeight: visible ? noticeText.implicitHeight+24 : 0; radius: 12; color: Theme.tint
                Text { id: noticeText; anchors.fill: parent; anchors.margins: 12; text: owner.notice; textFormat: Text.PlainText; color: Theme.ink; wrapMode: Text.WordWrap; font.pixelSize: 12 }
            }
            Rectangle { Layout.fillWidth: true; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin; visible: !!window.status.pause_reason; Layout.preferredHeight: visible ? pauseContents.implicitHeight+24 : 0; radius: 12; color: Theme.riskTint
                RowLayout { id: pauseContents; anchors.fill: parent; anchors.margins: 12
                    Copy { Layout.fillWidth: true; text: (window.status.pause_reason || {}).code==="wechat_burst_capacity" ? "连续消息过多，已暂停访问。请核对后重新授权。" : "服务遇到问题，已停止访问。请核对后重新授权。" }
                    ButtonX { text: "查看授权"; onClicked: window.openAccess(window.accessLevel) }
                }
            }
            StackLayout { id: pages; objectName: "contentViewport"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.leftMargin: Theme.margin; Layout.rightMargin: Theme.margin; currentIndex: window.page
                ConversationWorkspace { controller: owner; connected: window.connected; accessLevel: window.accessLevel
                    accessSummary: window.scopeActive ? (window.backend.grants || []).length + " 个私聊 · " + window.allowance(window.autoReply.remaining) : "按需授权微信访问"
                    onPermissionsRequested: function(level){window.openAccess(level)}
                    onOpenProject: function(target){window.page=target}
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
                                ButtonX { text: "恢复原设置"; enabled: !window.previewMode && owner.restoreAvailable; onClicked: restoreDialog.open() }
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
                        Field { id: permissionSearch; Layout.fillWidth: true; placeholderText: "搜索会话"; Accessible.name: "搜索会话权限" }
                        Caption { Layout.fillWidth: true; visible: (window.backend.conversations || []).length>40; text: "共 " + (window.backend.conversations || []).length + " 个会话，每次显示最多 40 个搜索结果。" }
                        Repeater { model: window.page===3 ? (window.backend.conversations || []).filter(function(c){return (c.display_name+" "+c.conversation_id).toLowerCase().indexOf(permissionSearch.text.toLowerCase())>=0}).slice(0,40) : []; delegate: Panel {
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
                                    ButtonX { text: window.independentService ? "设置授权范围" : "授权本地读取"; primary: true; enabled: window.connected; onClicked: {if(window.independentService){window.autoTargets=[modelData.conversation_id];window.autoAll=false;window.page=6}else{window.selectedConversation=modelData.conversation_id;window.selectedLabel=modelData.display_name;grantDialog.open()}} }
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
                SettingsPage { id: settingsPage; objectName: "settingsPage"; controller: owner; connected: window.connected; scopeActive: window.scopeActive; systemReady: window.systemReady; independentService: window.independentService; darkMode: window.darkMode; accessLevel: window.accessLevel
                    onSetupRequested: {setupDialog.step=0;setupDialog.open()}
                    onAccessRequested: function(level){window.openAccess(level)}
                    onStopRequested: stopDialog.open()
                    onRevokeRequested: revokeDialog.open()
                    onPageRequested: function(page){window.page=page}
                    onThemeRequested: function(dark){window.darkMode=dark}
                    onHooksRequested: hooksDialog.open()
                    onAssistantRequested: function(preferences){window.assistantDraft=preferences;assistantDialog.open()}
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
                                    ButtonX { objectName: "reviewContact_"+modelData.id; text: "查看并授权"; onClicked: {window.authorizationRequest=modelData;authorizationDialog.open()} }
                                    ButtonX { objectName: "denyContact_"+modelData.id; visible: window.status.contact_requests_supported===true; text: "拒绝"; onClicked: owner.denyAuthorization(modelData.id) }
                                }
                            }
                        }
                        Repeater { model: window.approvals; delegate: JobRow { required property var modelData; Layout.fillWidth: true; job: modelData } }
                    }
                }

            }
            Item { objectName: "statusBar"; Layout.fillWidth: true; Layout.preferredHeight: 0 }

        }
    }

    AccessDialog { id: accessEditor; objectName: "accessDialog"; anchors.centerIn: parent
        onApplyRequested: function(targets,minutes,replies,level,overwrite,policy,idle){owner.applyScope(targets,minutes,replies,level,overwrite,policy,idle)}
        onStopped: stopDialog.open()
        onBindingRequested: {if(setupDialog.resumeAfterAccess){setupDialog.resumeAfterAccess=false;setupDialog.step=2;Qt.callLater(function(){setupDialog.open()})}else{window.page=6;settingsPage.section=1}}
        onClosed: if(setupDialog.resumeAfterAccess){setupDialog.resumeAfterAccess=false;Qt.callLater(function(){setupDialog.step=3;setupDialog.open()})}
    }
    Onboarding { id: setupDialog; objectName: "setupDialog"; controller: owner; anchors.centerIn: parent
        onAccessRequested: function(level){resumeAfterAccess=true;close();Qt.callLater(function(){window.openAccess(level)})}
        onAssistantRequested: function(preferences){resumeAfterAssistant=true;close();window.assistantDraft=preferences;Qt.callLater(function(){assistantDialog.open()})}
    }
    Dialog { id: riskDialog; objectName: "fullAccessRiskDialog"; anchors.centerIn: parent; width: Math.min(540,window.width-80); modal: true; padding: 28; title: "开启完全访问？"; header: null; closePolicy: Popup.CloseOnEscape
        property bool continuing: false
        onOpened: continuing=false
        onClosed: {if(continuing)Qt.callLater(function(){accessEditor.open()});else if(setupDialog.resumeAfterAccess){setupDialog.resumeAfterAccess=false;Qt.callLater(function(){setupDialog.open()})}}
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 160 : 0 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.motionEnabled ? 100 : 0 } }
        background: GlassPanel { radius: 26 }
        Overlay.modal: Item {
            MultiEffect { anchors.fill: parent; source: appContent; blurEnabled: true; blur: 1.0; blurMax: 32; autoPaddingEnabled: false }
            Rectangle { anchors.fill: parent; color: window.darkMode ? "#6B000000" : "#3D20352A" }
        }
        contentItem: ColumnLayout { spacing: 20
            Copy { text: "开启完全访问？"; font.pixelSize: 22; font.weight: Font.DemiBold }
            Rectangle { width: 44; height: 44; radius: 14; color: Theme.riskTint; Icon { anchors.centerIn: parent; name: "warning"; ink: Theme.danger; width: 24; height: 24 } }
            Copy { Layout.fillWidth: true; text: "微信内容将发送给模型分析，并可自动回复。本人 /agent 任务还能使用绑定 Codex 对话的上下文与已授权工具。"; font.pixelSize: 15 }
            Caption { Layout.fillWidth: true; text: "可能发生错误回复、信息披露或文件变更。普通联系人不会获得任务权限；敏感操作仍需确认，发送结果不确定时不会重发。

下一步仍需核对具体联系人、期限和次数，并完成本机认证。" }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ButtonX { text: "取消"; onClicked: riskDialog.close(); Component.onCompleted: forceActiveFocus() }
                ButtonX { objectName: "fullAccessContinue"; text: "已知风险，继续"; danger: true; background: Rectangle { radius: 11; color: Theme.riskTint; border.color: Theme.riskBorder }
                    onClicked: {riskDialog.continuing=true;riskDialog.close()} }
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
        contentItem: Copy { text: "目标：" + (window.authorizationRequest.target || "") + "\n用途：" + (window.authorizationRequest.reason || "") + "\n\n将由本人核对稳定身份、读取/模型披露范围及是否允许回复，再通过本机认证签署。已有会话会按剩余时间和次数替换，旧待办取消；没有合格导航绑定时不新增发送权限。申请和聊天内容本身不能授予权限。" }
        onAccepted: owner.approveAuthorization(window.authorizationRequest.id)
    }
    Dialog { id: autoDialog; anchors.centerIn: parent; width: Math.min(560,window.width-60); modal: true; title: "确认自动回复授权"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "目标：" + (window.autoAll ? "当前已核验的全部可用私聊；排除群、公众号、系统会话" : window.autoTargets.map(window.targetName).join("、")) + "\n时长：" + (window.autoMinutes ? window.autoMinutes + " 分钟" : "不限时长，直到停止") + "，回复：" + (window.autoReplies ? "最多 " + window.autoReplies + " 次" : "不限次数") + "。\n\n允许把所选私聊的新消息发给 Codex 生成回复，再自动发送到原私聊。发送时微信会置前；请勿同时操作输入区。" + (window.overwriteDrafts ? "强制覆盖已开启，将清空已有输入。" : "检测到已有输入将停止，微信提示文字不算草稿。") + "身份或附件状态无法核对时仍停止。\n\n接下来需要本机系统身份认证，单次原生提交凭据保持短期；不限会话只在当前服务中续发，停止立即撤权。" + (window.selfAgentAccess ? "\n\n本人任务访问已选择：/agent 命令将交给绑定 Codex 对话及其已授权工具，敏感操作仍单独确认。" : "\n\n本人私聊仅使用普通回复权限。") }
        onAccepted: owner.startAutomatic(window.autoAll ? ["*"] : window.autoTargets,window.autoMinutes,window.autoReplies,window.overwriteDrafts,window.selfAgentAccess)
    }
    Dialog { id: selfAgentDialog; objectName: "selfAgentDialog"; anchors.centerIn: parent; width: Math.min(560,window.width-60); modal: true; title: "开启本人任务访问？"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "仅本人微信 ID 的私聊。以 /agent 开头的新文字将进入所选 Codex 对话，可使用该对话已授权的工具及上下文。\n\n普通联系人不会获得此权限。命令和文件变更仍会单独请求确认；权限扩大仍需本机身份认证。正在运行的任务会先完成，结果不确定时不重做。\n\n保存选择后，还需在开启服务时核对完整范围并完成系统认证。" }
        onAccepted: window.selfAgentAccess=true
    }
    Dialog { id: assistantDialog; anchors.centerIn: parent; width: Math.min(540,window.width-60); modal: true; title: "保存助理设置？"; standardButtons: Dialog.Cancel | Dialog.Ok
        onClosed: if(setupDialog.resumeAfterAssistant){setupDialog.resumeAfterAssistant=false;Qt.callLater(function(){setupDialog.open()})}
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "绑定对话：" + (window.assistantDraft.thread_title || "未选择") + "\n回复署名：" + (window.assistantDraft.attribution ? "显示" : "不显示") + "\n\n人设与回复风格将在下次开启时使用。保存不会授予读取、披露或发送权限。" }
        onAccepted: owner.saveAssistant(window.assistantDraft)
    }
    Dialog { id: stopDialog; objectName: "stopDialog"; anchors.centerIn: parent; width: Math.min(500,window.width-60); modal: true; title: "停止自动回复？"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "停止监听并撤销当前读取、披露和发送权限。本人任务也将停止交接；已经提交的操作不会重试。无需再次身份认证。" }
        onAccepted: owner.stopAutomatic()
    }
    Dialog { id: hooksDialog; anchors.centerIn: parent; width: Math.min(520,window.width-60); modal: true; title: "连接会话状态？"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "将添加四项 Codex 会话事件，用于等待当前任务结束。仅转发会话编号和忙闲状态，不记录提示词；需在 Codex 中审核。" }
        onAccepted: owner.installHooks()
    }
    Dialog { id: restoreDialog; anchors.centerIn: parent; width: Math.min(500,window.width-60); modal: true; title: "恢复连接设置？"; standardButtons: Dialog.Cancel | Dialog.Ok
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Copy { text: "恢复本次连接前备份的 Codex 设置。若文件已被其他操作修改，将停止恢复并保留现状。" }
        onAccepted: owner.restoreConfig()
    }
    Dialog { id: agentActionDialog; anchors.centerIn: parent; width: Math.min(720,window.width-60); height: Math.min(560,window.height-80); modal: true; title: (owner.agentApproval || {}).title || "确认任务操作"; standardButtons: Dialog.Cancel | Dialog.Ok; closePolicy: Popup.NoAutoClose
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: ColumnLayout { spacing: 16
            Caption { Layout.fillWidth: true; text: "来自本人私聊的任务。请核对精确操作；仅批准这一次，不保存放行规则。" }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                TextArea { text: (owner.agentApproval || {}).detail || ""; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.ink; background: Rectangle { radius: 12; color: Theme.canvas } }
            }
        }
        onAccepted: owner.decideAgent(true)
        onRejected: owner.decideAgent(false)
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
