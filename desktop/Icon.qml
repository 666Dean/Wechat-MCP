import QtQuick
Canvas {
    id: icon
    property string name: "grid"
    property color ink: "#74817B"
    implicitWidth: 20; implicitHeight: 20
    onNameChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        var c=getContext("2d");c.reset();c.scale(width/24,height/24)
        c.strokeStyle=ink;c.lineWidth=1.65;c.lineCap="round";c.lineJoin="round"
        function line(points){c.beginPath();c.moveTo(points[0][0],points[0][1]);for(var i=1;i<points.length;i++)c.lineTo(points[i][0],points[i][1]);c.stroke()}
        function box(x,y,w,h){c.beginPath();c.roundedRect(x,y,w,h,1.5,1.5);c.stroke()}
        if(name==="grid"){box(3,3,7,7);box(14,3,7,7);box(3,14,7,7);box(14,14,7,7)}
        else if(name==="plug"){line([[8,3],[8,8]]);line([[16,3],[16,8]]);box(6,8,12,8);line([[12,16],[12,21]])}
        else if(name==="inbox"){line([[3,14],[6,5],[18,5],[21,14],[21,20],[3,20],[3,14],[8,14],[10,17],[14,17],[16,14],[21,14]])}
        else if(name==="brief"){box(5,3,14,18);line([[8,8],[16,8]]);line([[8,12],[16,12]]);line([[8,16],[13,16]])}
        else if(name==="shield"){line([[12,3],[20,6],[19,15],[16,19],[12,22],[8,19],[5,15],[4,6],[12,3]]);line([[9,12],[11,14],[15,9]])}
        else if(name==="activity"){box(3,5,18,14);line([[5,12],[8,12],[10,8],[14,16],[16,12],[19,12]])}
        else if(name==="clip"){c.beginPath();c.moveTo(8,14);c.lineTo(8,7);c.bezierCurveTo(8,1,18,1,18,7);c.lineTo(18,16);c.bezierCurveTo(18,24,5,24,5,16);c.lineTo(5,7);c.stroke();line([[11,7],[11,15],[14,15],[14,7]])}
        else if(name==="settings"){line([[3,6],[9,6]]);line([[13,6],[21,6]]);box(9,4,4,4);line([[3,12],[15,12]]);line([[19,12],[21,12]]);box(15,10,4,4);line([[3,18],[6,18]]);line([[10,18],[21,18]]);box(6,16,4,4)}
        else if(name==="check"){c.beginPath();c.arc(12,12,9,0,Math.PI*2);c.stroke();line([[8,12],[11,15],[16,9]])}
        else if(name==="clock"){c.beginPath();c.arc(12,12,9,0,Math.PI*2);c.stroke();line([[12,7],[12,12],[16,14]])}
        else if(name==="message"){line([[4,5],[20,5],[20,16],[12,16],[6,21],[6,16],[4,16],[4,5]])}
        else if(name==="arrow"){line([[5,12],[19,12],[14,7]]);line([[19,12],[14,17]])}
        else if(name==="refresh"){c.beginPath();c.arc(12,12,8,.8,5.9);c.stroke();line([[20,3],[20,9],[14,9]])}
        else if(name==="info"){c.beginPath();c.arc(12,12,9,0,Math.PI*2);c.stroke();line([[12,11],[12,17]]);line([[12,7],[12,7.1]])}
        else if(name==="warning"){line([[12,3],[22,21],[2,21],[12,3]]);line([[12,9],[12,14]]);line([[12,17],[12,17.1]])}
        else if(name==="lock"){box(5,10,14,11);c.beginPath();c.arc(12,10,5,Math.PI,Math.PI*2);c.stroke();line([[12,14],[12,17]])}
    }
}
