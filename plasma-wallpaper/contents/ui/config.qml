import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_Url: urlField.text
    property real cfg_Zoom: 1.0
    property alias cfg_ReloadSeconds: reloadSpin.value
    property alias cfg_PauseWhenCovered: pauseBox.checked

    // The defaults (Plasma fills them in; without them it logs warnings)
    property string cfg_UrlDefault
    property real cfg_ZoomDefault
    property int cfg_ReloadSecondsDefault
    property bool cfg_PauseWhenCoveredDefault

    // Zoom is a real and the box an integer percent: follow the value when it
    // changes from outside too (the Defaults button).
    onCfg_ZoomChanged: zoomSpin.value = Math.round(cfg_Zoom * 100)

    QQC2.TextField {
        id: urlField
        Kirigami.FormData.label: "URL:"
        Layout.fillWidth: true
        placeholderText: "https://…"
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.75
        text: "Pixel City: add ?quality=low on a slow computer, ?seed=123 for the same city every time."
    }

    QQC2.SpinBox {
        id: zoomSpin
        Kirigami.FormData.label: "Zoom:"
        from: 25; to: 500; stepSize: 25
        editable: true
        value: Math.round(page.cfg_Zoom * 100)
        onValueModified: page.cfg_Zoom = value / 100
        textFromValue: (v, locale) => v + "%"
        valueFromText: (text, locale) => parseInt(text) || 100
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.75
        text: "Pixel art stays sharp at whole multiples: 100%, 200%, 300%."
    }

    QQC2.SpinBox {
        id: reloadSpin
        Kirigami.FormData.label: "Reload every:"
        from: 0; to: 86400; stepSize: 60
        editable: true
        textFromValue: (v, locale) => v === 0 ? "never" : v + " s"
        valueFromText: (text, locale) => parseInt(text) || 0
    }

    QQC2.CheckBox {
        id: pauseBox
        Kirigami.FormData.label: "Power saving:"
        text: "Pause under maximized or full-screen windows"
    }
}
