 function cT(id)
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

    tstr = "<b>y = &nbsp; (</b>";
    count = 0;
    totalCount = 0;
    for (i=0; i<cells.length; i++) // Numerator
    {
        if (cells[i].id.toString().substring(0,5) != "CPX_N")
        {
            continue;
        }

        if (isSelected(cells[i]))
        {
            if (count > 0)
                tstr += "&nbsp+ ";
            if (cells[i].id.toString().substring(5,6) == "0")
                tstr += '<b>' + c[totalCount] + '</b>';
            else
                tstr += '<b>' + c[totalCount] + '(&nbsp;</b>' + cells[i].innerHTML + '<b>&nbsp;)</b>';
            count += 1;
            totalCount += 1;
        }
    }
    tstr += "<b>) &nbsp; / &nbsp; (1.0 + </b>";
    count = 0;
    for (i=0; i<cells.length; i++) // Denominator
    {
        if (cells[i].id.toString().substring(0,5) != "CPX_D")
        {
            continue;
        }

        if (isSelected(cells[i]))
        {
            if (count > 0)
                tstr += "&nbsp+ ";
            if (cells[i].id.toString().substring(5,6) == "0")
                tstr += '<b>' + c[totalCount] + '</b>';
            else
                tstr += '<b>' + c[totalCount] + '(&nbsp;</b>' + cells[i].innerHTML + '<b>&nbsp;)</b>';
            count += 1;
            totalCount += 1;
        }
    }
    tstr += "<b>)</b>";

    for (i=0; i<cells.length; i++) // Offset
    {
        if (cells[i].id.toString().substring(0,5) != "CPX_O")
        {
            continue;
        }

        if (isSelected(cells[i]))
        {
            tstr += ' &nbsp; + &nbsp; <b>' + c[totalCount] + '</b>';
        }
    }

    document.getElementById('FUNCTION').innerHTML = tstr;
 }

 function readPolyFlags()
 {
    cells = pickCells();
    for (i=0; i<cells.length; i++)
    {
        value = isSelected(cells[i]) ? 'True' : 'False';
        if (cells[i].id.toString().substring(0,5) == 'CPX_N')
        {
            document.forms[0].elements['polyRational_X_N' + cells[i].id.toString().substring(5)].value = value;
        }
        if (cells[i].id.toString().substring(0,5) == 'CPX_D')
        {
            document.forms[0].elements['polyRational_X_D' + cells[i].id.toString().substring(5)].value = value;
        }
        if (cells[i].id.toString().substring(0,5) == 'CPX_O')
        {
            document.forms[0].elements['polyRational_OFFSET'].value = value;
        }
    }
 }
