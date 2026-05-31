 function cT(id, unusedFor3D)
 {
    cells = pickCells();
    count = 0;
    for (i=0; i<cells.length; i++)
    {
        if (isSelected(cells[i]))
        {
            count += 1;
        }
    }

    target = document.getElementById(id);
    if ((count >= maxCoeffs) && (!isSelected(target)))
    {
        alert(warning);
        return;
    }

    setSelected(target, !isSelected(target));

    tstr = "<b>z = </b>";
    str = "";
    count = 0;
    for (i=0; i<cells.length; i++)
    {
        if (isSelected(cells[i]))
        {
            if (cells[i].id.toString() == "CPX0Y0")
            {
                str += '<b>' + cells[i].innerHTML + '</b>';
            }
            else
            {
                if (count > 0)
                    tstr += "&nbsp;<b>+</b> ";
                tstr += '<b>' + c[count] + '(&nbsp;</b>' + cells[i].innerHTML + '<b>&nbsp;)</b>';
                count += 1;
            }
        }
    }
    if (tstr == "<b>z = </b>")
         tstr += str;
    else
        if (str != "")
            tstr += "&nbsp;<b>+</b> " + str;
    document.getElementById('FUNCTION').innerHTML = tstr;
 }
