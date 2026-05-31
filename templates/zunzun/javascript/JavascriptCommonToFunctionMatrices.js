 c = "abcdfghijkmnpqrstuvwxyzABCDEFGHIJKLMNPQRSTUVWXYZ".split("")
 maxCoeffs = 15
 warning = 'The limit is currently ' + maxCoeffs + ' selections.'

 // Cell selection state lives in the "selected" CSS class (see static/custom.css
 // td.pick.selected). isSelected/setSelected are the single read/write points so
 // the matrix scripts never touch presentation directly.
 function pickCells() {
     return document.querySelectorAll('td.pick');
 }
 function isSelected(cell) {
     return cell.classList.contains('selected');
 }
 function setSelected(cell, on) {
     cell.classList.toggle('selected', on);
 }
