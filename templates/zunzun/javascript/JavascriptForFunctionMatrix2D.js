 function cT(id, polyfunctionalFlag)
 {
    if (!toggleWithLimit(id)) return;

    cells = pickCells();
    tstr = "<b>y = </b>";
    str = "";
    count = 0;
    for (i=0; i<cells.length; i++)
    {
        if (isSelected(cells[i]))
        {
            if (polyfunctionalFlag == 1)
            {
                if (cells[i].id.toString() == "CPX0")
                {
                    str += '<b>' + cells[i].innerHTML + '</b>';
                }
                else
                {
                    if (count > 0)
                        tstr += "&nbsp+ ";
                    tstr += '<b>' + c[count] + '(&nbsp;</b>' + cells[i].innerHTML + '<b>&nbsp;)</b>';
                    count += 1;
                }
            }
            else
            {
                if (count > 0)
                    tstr += "&nbsp+ ";
                tstr += '<b>' + c[count] + '</b>' + cells[i].innerHTML;
                count += 1;
            }
        }
    }
    if (tstr == "<b>y = </b>")
         tstr += str;
    else
        if (str != "")
            tstr += "&nbsp;<b>+</b> " + str;
    document.getElementById('FUNCTION').innerHTML = tstr;
 }
