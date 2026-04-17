Welcome to zunzunsite3, a Django site in Python 3 for curve fitting 2D
and 3D data that can output source code in several computing languages
and run a genetic algorithm for initial parameter estimation. Includes
orthogonal distance and relative error regressions. Generates PDF files
and surface animations. Based on code from zunzun.com. 

You will need to install scipy, matplotlib, django, bs4, imagemagick
gifsicle and reportlab to run this software, alog with psutil.  On
Debian and Ubuntu, you can run the following:

apt-get install python3-scipy python3-matplotlib python3-pil
apt-get install python3-django python3-bs4
apt-get install python3-reportlab imagemagick gifsicle
apt-get install python3-psutil

then install the pyeq3 fitting code with these commands:

apt-get install python3-pip
pip3 install pyeq3


You can now cd to the project's top-level directory.
First-time setup creates the session database:

python3 manage.py migrate

Then run the django development server with:

python3 manage.py runserver

and open the url http://127.0.0.1:8000/ in a browser. Cool!


NOTES: the code uses Unix-style process forking, and this
is not available on the  Windows operating system.

My tests show that while both mod_wsgi and gunicorn work fine
for Django production servers, the uwsgi process model would not
allow os.fork() calls to work as required for this software.
