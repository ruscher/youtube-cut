import QtQuick
import "."

// Ícone vetorial colorido pelo tema (servido por gui/icons.py).
// Item externo: Image não permite definir tamanho implícito, e layouts usam ele.
Item {
    id: root
    property string name
    property color color: Theme.text
    property int size: 18

    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.fill: parent
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: root.name ? "image://icon/" + root.name + "/" + root.color.toString().substring(1) : ""
    }
}
