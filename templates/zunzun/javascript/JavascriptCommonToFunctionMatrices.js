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
     if (cell.dataset.flag) {
         document.forms[0].elements[cell.dataset.flag].value = on ? 'True' : 'False';
     }
 }

 // Shared count -> cap -> toggle prologue for every matrix's cT(). Returns
 // false (without toggling) when the selection cap is already reached, true
 // after toggling the target cell.
 function toggleWithLimit(id) {
     cells = pickCells();
     count = 0;
     for (i=0; i<cells.length; i++) {
         if (isSelected(cells[i])) {
             count += 1;
         }
     }
     target = document.getElementById(id);
     if ((count >= maxCoeffs) && (!isSelected(target))) {
         alert(warning);
         return false;
     }
     setSelected(target, !isSelected(target));
     return true;
 }
