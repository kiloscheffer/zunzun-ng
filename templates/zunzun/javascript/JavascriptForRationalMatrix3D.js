 function cT(id)
 {
    if (ns4)
    {
        len = d.layers.length;
        count = 0;
        for (i=0; i<len; i++)
        {
            if ((d.layers[i].id.toString().substring(0,3) == "CPX") && (d.layers[i].style.backgroundColor.replace(/\s/g, '') == w))
            {
                count += 1;
            }
        }
        if ((count >= maxCoeffs) && (d.layers[id].style.backgroundColor.replace(/\s/g, '') == lg))
        {
            alert(warning);
            return;
        }

        if (d.layers[id].style.backgroundColor.replace(/\s/g, '') == lg)
        {
            d.layers[id].style.backgroundColor = w;
            d.layers[id].borderStyle = ins;
        }
        else
        {
            d.layers[id].style.backgroundColor = lg;
            d.layers[id].borderStyle = os;
        }

        tstr = "<b>z = </b>";
        str = "";
        count = 0;
        for (i=0; i<len; i++)
        {
            if (d.layers[i].id.toString().substring(0,3) != "CPX")
            {
                continue;
            }

            if (d.layers[i].style.backgroundColor.replace(/\s/g, '') == w)
            {
                if (d.layers[i].id.toString() == "CPX0Y0")
                {
                    str += '<b>' + d.layers[i].innerHTML + '</b>';
                }
                else
                {
                    if (count > 0)
                        tstr += "&nbsp+ ";
                    tstr += '<b>' + c[count] + '(&nbsp;</b>' + d.layers[i].innerHTML + '<b>&nbsp;)</b>';
                    count += 1;
                }
            }
        }
        if (tstr == "<b>z = </b>")
             tstr += str;
        else
            if (str != "")
                tstr += "&nbsp;<b>+</b> " + str;
        d.layers['FUNCTION'].innerHTML = tstr;
    }

    if (ie4)
    {
        len = d.all.length;
        count = 0;
        for (i=0; i<len; i++)
        {
            if ((d.all[i].id.toString().substring(0,3) == "CPX") && (d.all[i].style.backgroundColor.replace(/\s/g, '') == w))
            {
                count += 1;
            }
        }
        if ((count >= maxCoeffs) && (d.all[id].style.backgroundColor.replace(/\s/g, '') == lg))
        {
            alert(warning);
            return;
        }

        if (d.all[id].style.backgroundColor.replace(/\s/g, '') == lg)
        {
            d.all[id].style.backgroundColor = w;
            d.all[id].style.borderStyle= ins;
        }
        else
        {
            d.all[id].style.backgroundColor = lg;
            d.all[id].style.borderStyle = os;
        }

        tstr = "<b>z = </b>";
        str = "";
        count = 0;
        for (i=0; i<len; i++)
        {
            if (d.all[i].id.toString().substring(0,3) != "CPX")
            {
                continue;
            }

            if (d.all[i].style.backgroundColor.replace(/\s/g, '') == w)
            {
                if (d.all[i].id.toString() == "CPX0Y0")
                {
                    str += '<b>' + d.all[i].innerHTML + '</b>';
                }
                else
                {
                    if (count > 0)
                        tstr += "&nbsp;<b>+</b> ";
                    tstr += '<b>' + c[count] + '(&nbsp;</b>' + d.all[i].innerHTML + '<b>&nbsp;)</b>';
                    count += 1;
                }
            }
        }
        if (tstr == "<b>z = </b>")
             tstr += str;
        else
            if (str != "")
                tstr += "&nbsp;<b>+</b> " + str;
        d.all['FUNCTION'].innerHTML = tstr;
    }
 }

 function readPolyFlags()
 {
    if (ns4)
    {
        len = document.layers.length;
        for (i=0; i<len; i++)
        {
        	if(document.layers[i].id.toString().substring(0,3) == 'CPX')
        	{
	            if (document.layers[i].style.backgroundColor.replace(/\s/g, '') == lg)
	            {
	                eval("document.forms[0].elements.polyFunctional_X" + document.layers[i].id.toString().substring(3) + ".value = 'False'");
	            }
	            if (document.layers[i].style.backgroundColor.replace(/\s/g, '') == w)
	            {
	                eval("document.forms[0].elements.polyFunctional_X" + document.layers[i].id.toString().substring(3) + ".value = 'True'");
	            }
            }
        }
    }

    if (ie4)
    {
        len = document.all.length;
        for (i=0; i<len; i++)
        {
        	if(document.all[i].id.toString().substring(0,3) == 'CPX')
        	{
	            if (document.all[i].style.backgroundColor.replace(/\s/g, '') == lg)
	            {
	                eval("document.forms[0].elements.polyFunctional_X" + document.all[i].id.toString().substring(3) + ".value = 'False'");
	            }
	            if (document.all[i].style.backgroundColor.replace(/\s/g, '') == w)
	            {
	                eval("document.forms[0].elements.polyFunctional_X" + document.all[i].id.toString().substring(3) + ".value = 'True'");
	            }
	        }
        }
    }
}
