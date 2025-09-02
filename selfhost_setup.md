<p align="center">
  <img src="assets/ermlogo.png" alt="ERM Bot Logo">
</p>


<h1 align="center">ERM Bot Self-hosting guide</h1>

<p align="center">
  This guide is designed to help you set up ERM on your own server or local machine, whether you're using Windows or a Debian/Ubuntu-based Linux distribution.
  <br>
  ERM is a powerful moderation and staff management bot, designed for Emergency Response: Liberty County & Maple County Communities. By self-hosting, you can customise ERM to your own liking, add new features, and contribute to its development!
  <br>
  <br>
  This document will walk you through the steps needed to run ERM on your own machine, including:
</p>
<ul>
  <li>Preparing your environment</li>
  <li>Installing dependencies</li>
  <li>Configuring the bot</li>
  <li>Running and troubleshooting</li>
</ul>

<h2 align="center">Contents:</h2>
<ul>
  <li><a href="#windows-self-host-guide">Self-Hosting on Windows</a></li>
    <ul>
      <li><a href="#windows-prerequisites">Prerequisites</a></li>
      <li><a href="#windows-packages-dependencies">Installing packages and dependencies</a></li>
      <li><a href="#windows-env-config">Environment Configuration(<code>.env</code> Setup)</a></li>
      <li><a href="#windows-final-setup-running">Final Bot Setup and Running </a><li>
    </ul>
  <li><a href="#ubuntu-debian-self-host-guide">Self-Hosting on Ubtunu/Debian-based systems</a></li>
    <ul>
      <li><a href="#ubuntu-debian-prerequisites">Prerequisites</a></li>
			<li><a href="#ubuntu-debian-packages-dependencies">Installing Packages and Dependencies</a></li>
			<li><a href="#ubuntu-debian-env-config">Environment Configuration (<code>.env</code> Setup)</a></li>
      <li><a href="#ubuntu-debian-final-setup-running">Final Bot Setup and Running </a></li>
    </ul>
</ul>
<h1></h1>
<p align="center">
  <br>
<b>DISCLAIMER:</b>
  ERM is licensed under the Attribution-NonCommercial-ShareAlike (CC BY-NC-SA) license. This license allows for the copy, distribution, and creation of adaptations of the material for non-commercial purposes, as long as proper attribution is given to the original creator and any adaptations are licensed under the same terms.
  <br>
  <br>
  The CC BY-NC-SA license requires the following elements:
</p>
<ul>
  <li>BY: Credit must be given to the original creator</li>
  <li>NCL The material can only be used for non-commercial purposes</li>
  <li>SA: Adaptations must be licensed under the same terms</li>
</ul>
<p align="center">
  This means that your self-hosted bot must give credit to the original creators, you must not sell it, charge money for its use, include it in paid services, or make a profit from it, and any adaptations must also be licensed under the Attribution-NonCommercial-ShareAlike (CC BY-NC-SA) license.
</p>

<h1 id="windows-self-host-guide" align="center">Windows Self-Host Guide</h1>
<p align="center">This section will explain how to self-host ERM on <b>Windows 10/11</b>. May or may not work on Windows server, or other distributions. </p>
<h2 id="windows-prerequisites"align="center">Prerequisites</h2>
<p align="center">You will need these before your bot can go online:</p>

<br>
<ul>
	<li>The ERM Repository</li>
	<li>Windows Terminal or Command Prompt (PowerShell also works)</li>
  <li>Python version 3.10+ for Windows</li>
  <li>Python3 pip (Included with Python 3.4+)</li>
	<li>pynacl (Optional, use if you want voice features)</li>
  <li>Git for Windows</li>
  <li>MongoDB Atlas URI</li>
  <li>Discord Bot Token</li>
</ul>
<br>

<h2 id="windows-packages-dependencies" align="center">Installing Packages and Dependencies</h2>
<p align="center"> You will need to download some packages for this to work, so let's walk through them. <br>

<h3 align="center">Python 3.10+</h3>
<p align="center">First, you will need to <a href="https://www.python.org/downloads/windows/">Download Python</a>. Run the installer, and make sure to check <code>Add Python.exe to PATH</code>, or else this won't work. Then, press <code>Install now</code> and wait for the install to finish. 
  (<b>You can customise your installation, but you will need to download pip & venv module.</b>)</p>

<h3 align="center">Git</h3>
<p align="center">You will also need to <a href="https://git-scm.com/downloads/win">download Git.</a> After downloading the latest version, follow the setup instructions. <b>This will give you Git Bash, but you can use command prompt or powershell</b>. 

<h3 align="center">Cloning ERM</h3>
<p align="center">To download the ERM repository, you can either:</p>
<ul>
  <li>Download the ZIP from GitHub and extract it.</li>
  <li>Or use Git:</li>
</ul>
<p align="center">To use git, open command prompt (<b>Win + R</b>, type in <b>cmd</b> and press <b>enter</b>) and run the following:</p>
<pre><code>git clone https://github.com/mikeyerm/ERM.git</code></pre>

<p align="center"> Once you have those installed, we now need to make a venv, and install our packages. </p>
<br>

<h3 align="center">Setting up the Virtual Environment</h3>
<p align="center">Navigate to your ERM folder by doing the following:</p>
<pre><code>cd C: \path\to\ERM-main</code></pre>
<p align="center">Then, run these next two commands:</p>
<pre><code>python -m venv venv<br> 
venv\Scripts\activate</code></pre>
<p align="center">If your command prompt says <code>(venv)</code>, you have successfully set up the virtual environment. </p>

<h3 align="center">Installing Requirements</h3>
<p align="center">Upgrade pip & tools with the following: </p>
<pre><code>pip install --upgrade pip setuptools wheel</code></pre>
<p align="center">Then, you can install dependencies with this command:</p>
<pre><code>pip install -r requirements.txt</code></pre>

<h2 id="windows-env-config" align="center">Environment Configuration (<code>.env</code> Setup)</h2>
<p align="center">Congrats on making it past that stage! Now, your .env file must be configured to include things such as your Discord Bot Token, MongoDB Atlas URI, API keys, and more. 
Your <code>.env</code> file should be in your ERM-main folder, but might be called <code>.env.template</code>. 
Open the <code>.env</code> file in a code editor, such as Visual Studio Code, and edit the text. 
The following steps will explained how to fill out the <code>.env</code> file properly.
  
<br>
<b>Required for bot to function:</b></p>
<ul>
	<li>MongoDB Atlas URI</li>
	<li>Discord Bot Token</li>
	<li>Environment Type</li>
	<li>Custom Guild ID</li>
	<li>Panel API URL</li>
	<li>Sentry URL (Not <b>required</b> for bot to run, but recommended for error logging)</li>
</ul>

<h3 align="center">MongoDB Atlas URI</h3>
<p align="center">To get your <code>MONGO_URL</code>, you need to make a free MongoDB Atlas URI. <br>To do so, you need to <a href="https://www.mongodb.com/cloud/atlas/register">make an account with MongoDB</a> — it's free, and doesn't need a credit card. 
You can sign in with GitHub or Google, or just use your email. 
Once you have completed the sign-up process, you need to create a cluster. 
You should be able to do this by pressing the "Create Cluster" button. 
The Name, Provider and Region do not matter, simply press "Create Deployment" and wait for it to finish creating the cluster.
You should have gotten a popup asking you to connect to your cluster, and to make a database user, just press "create database user". 
To connect to your application, press the "Drivers" option, and copy the connection string. 
<br><b>Make sure to store this somewhere you will be able to access it from again</b>.
<br> Once done, go to "Network Access" on the sidebar, press "Add IP Address", click "Allow access from anywhere", and hit "Confirm".
 Paste the connecton string into the .env file after <code>MONGO_URL=</code>. 
<br>That should look like so, with your username, password and cluster name:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority
</code></pre>

<h3 align="center">Environment Type & Discord Bot Token</h3>
<p align="center">Next, we will change the Environment Type to <b>Custom</b>. Your ENVIRONMENT in your <code>.env</code> file should look like so:
<pre><code>ENVIRONMENT=CUSTOM</code></pre>
<br> 
<p align="center">To get your discord Bot Token, you need to create an application in the <a href="https://discord.com/developers/applications">Discord Developer Portal</a>.
Once you have a bot token, you need to add another line into your <code>.env</code> file. Since our environment type is <code>CUSTOM</code>, we can't use <code>PRODUCTION_BOT_TOKEN</code> or <codE>DEVELOPMENT_BOT_TOKEN</codE></p>Add a line anywhere, and type <code>CUSTOM_BOT_TOKEN=</code>. Paste your bot token after that. <br>
<br>
So far, your <code>.env</code> file should look like this: 
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL= <br>
PRODUCTION_BOT_TOKEN= <br>
DEVELOPMENT_BOT_TOKEN= <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
BLOXLINK_API_KEY=</code></pre>
<br>

<h3 align="center">Sentry Logging and Bloxlink API</h3>
<p align="center"><i>The following are not <b>required</b>, but some features might not work without a bloxlink API key.</i></p>
<p align="center">You do not need to fill out <code>PRODUCTION_BOT_TOKEN</code> or <code>DEVELOPMENT_BOT_TOKEN</code> if you have <code>ENVIRONMENT=CUSTOM</code> and <code>CUSTOM_BOT_TOKEN</code>. 
Unless you have a bloxlink API Key (which you can get from <a href="https://blox.link/dashboard/user/developer">here</a>), you do not need to fill it out. If you want error logging with Sentry, <a href="https://sentry.io/signup/">sign up here</a>, <b>Install Sentry</b>, select Python(vanilla) as the platform you want to monitor, press <b>configure SDK</b> (sentry-sdk has already been installed, you do not need to install it with pip again), and copy the URL in <code>dsn="yoursentrysdkurl"</code>. You need to edit <code>SENTRY_URL=</code> to <code>SENTRY_BASE_URL</code>, and then you can paste it into your <code>.env</code> file. <br>
<br> Your <code>.env</code> file should be looking like this:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL=yoursentrysdkurl <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
BLOXLINK_API_KEY=yourbloxlinkapikey</code></pre>

<h3 align="center">Custom Guild ID and Panel API URL</h3>
<p align="center">The following fields need to be added to your <code>.env</code> file for your bot to be able to function. <br></p>
<pre><code>CUSTOM_GUILD_ID=yourserverid <br>
PANEL_API_URL=[leave blank]</code></pre>
<p align="center">Your <code>.env</code> file should look like this now:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL=your://sentry.io.url/ <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
CUSTOM_GUILD_ID=yourserverid <br>
BLOXLINK_API_KEY=yourbloxlinkapikey <br>
PANEL_API_URL= [leave blank]</code></pre>
<p align="center">You can now save your <code>.env</code> file, and move onto the next step. That is everything that is required for your bot to host, everything else is just external APIs for er:lc, maple county, google sheets, etc. <br>
<b>Note: Make sure your file is saved as <code>.env</code>, not <code>.env.template</code> or something like <code>.env.txt</code>.</b></p>

<h2 id="windows-final-setup-running">
<p align="center">At the time of writing, the ERM repository is missing <code>utils/advanced.py</code>. The bot will not run without this file.  Thankfully, we can replicate the contents of the file pretty easily. </p>
<h3 align="center">Making missing <code>utils/advanced.py</code> file</h3>
<p align="center"> Make a new file inside of the <code>utils</code> folder, and title it <code>advanced.py</code>. Then, copy and paste the following into it:
<pre><code>
import discord<br>
<br>
class FakeMessage:<br>
    def __init__(self, content, author, channel, state):<br>
        self.content = content<br>
        self.author = author  <br>
        self.channel = channel <br>
        self.guild = author.guild if hasattr(author, 'guild') else None<br>
        self.created_at = discord.utils.utcnow()<br>
        self._state = state<br>
        self.attachments = []<br>
        self.mentions = []<br>
        self.mention_everyone = False<br>
        self.role_mentions = []<br>
        </code></pre>
        
<p align="center"> Once you have completed all previous steps, it is time to run your bot. This has to be done inside of the Virtual Environment we created — if you are no longer in that terminal, run the following commands:
<pre><code>cd ~/path/to/ERM-main<br>
python3 -m venv venv <br>
source venv/bin/activate </code></pre>
<p align="center">If your terminal has changed from this format: </p>
<pre><code>username@computername:~$</code></pre>
<p align="center"> to this: </p>
<pre><code>(venv) username@computername:~/path/to/ERM-main$ </code></pre>
<p align="center">You should be able to run the following command, which should start up your bot:</p>
<pre><code>python3 main.py</code></pre>
<p align="center">Well done! Your bot should now be running! If you close your terminal, or turn off your computer, your bot <b>will stop running</b>. If you want to safely stop the bot from running, press <code>Ctrl + C</code> inside of the terminal.


<h1 id="ubuntu-debian-self-host-guide" align="center">Ubuntu/Debian Self-Host Guide</h1>
<p align="center">This section will explain how to self-host ERM on <b>Debian/Ubuntu-based systems</b>, which includes Linux Mint, Pop!_OS, Zorin OS, Lubuntu, Xubuntu, and any other distribution that uses the <code>apt</code> package manager.</p>
<h2 id="ubuntu-debian-prerequisites" align="center">Prerequisites</h2>
<p align="center">You will need these before your bot can go online:</p>

<br>
<ul>
	<li>The ERM Repository</li>
	<li>A terminal that supports Bash (such as GNOME Terminal, Xfce Terminal, etc.)</li>
  <li>Python version 3.10+ </li>
  <li>Python3 pip (Python 3.4+ has pip enabled by default.)</li>
  <li>Python venv module (Optional, but you <b>will need it</b> if you are <b>depending on this guide</b> to know how to self-host ERM.)</li>
	<li>pynacl (Optional, only use if you want voice features)</li>
  <li>Git</li>
  <li>MongoDB Atlas URI</li>
	<li>Discord Bot Token</li>
</ul>
<br>

<h2 id="ubuntu-debian-packages-dependencies" align="center">Installing Packages and Dependencies</h2>
<p align="center"><b>Note: All packages are necessary for the entire bot to function, unless you are manually editing files to remove modules. These instructions rely on using <code>setuptools wheel</code> to read <a href="https://github.com/mikeyerm/ERM/blob/main/requirements.txt">requirements.txt</a> and install all packages required. This is the recommended method, unless you are using another method.</b> <br>
<br>
<h3 align="center">ERM Repository</h3>
<p align="center"> You can install the ERM repository by going <a href="https://github.com/mikeyerm/ERM/tree/main#">here</a>, pressing the green "code" button, and pressing "Download ZIP". Once done, extract the folder to somewhere you can store it, such as a folder on your Desktop, or straight on your desktop. </p>
<br>

<h3 align="center">Python, pip & venv</h3>
Next, you will need a few python packages to run the python files. To check if you have python & pip installed, run:
<br> <pre><code>python3 --version </code></pre>
<pre><code>pip --version </code></pre>
<br>
ERM runs on python 3.10, so make sure your python version is 3.10 or later. To check if you have venv installed, you need to run: <pre><code>python3 -m venv --help</code></pre>
<br> 
If you do not have the required files, you can install all three of them in one command by running: 
<br><pre><code>sudo apt update <br>
sudo apt install python3-venv python3-full -y</code></pre>

<h3 align="center">System Dependencies</h3>
<p align="center">Once you have those installed, you will need to install system dependencies for Levenshtein & pycryptodome. <br>
To install those system dependencies, run: 
<br><pre><code>sudo apt install build-essential libffi-dev python3-dev libssl-dev libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev -y</code></pre>
<p align="center"> This will install necessary system dependencies for Levenshtein and pycryptodome. <br>
<h3 align="center">Git</h3>
<p align="center">Next step is to install Git. You can install Git by running the following commands: 
<br><pre><code>sudo apt update<br>
sudo apt install git -y</code></pre>

<h3 align="center">Virtual Environment</h3>
<p align="center"> The next few commands involve setting up a <b>virtual environment</b>, which is best practice if you don't want to break your system. Replacing <code>~path/to/ERM-main</code> with the actual directory to where you put ERM-main, and with <b>~</b> representing your <b>home directory</b>(/home/username/), run the following command:</p>
<pre><code>cd ~/path/to/ERM-main</code></pre>
<p align="center">Your terminal should now include the location of your folder, and look something like this:</p>
<pre><code>username@computer-name:<b>~/path/to/ERM-main$</b></code></pre>
<p align="center">If it does, well done! If it doesn't, either try again or read the error message. Then, run these next 2 commands:</p>
<pre><code>python3 -m venv venv</code></pre>
<pre><code>source venv/bin/activate</code></pre>
<p align="center">Your terminal should now have <b>(venv)</b> at the start, looking like this:</p>
<pre><code>(venv) username@computer-name:<b>~/path/to/ERM-main$</b></code></pre>

<h3 align="center">Installing <a href="https://github.com/mikeyerm/ERM/blob/main/requirements.txt">Requirements.txt</a>
<p align="center">Next, we will use pip/setuptools/wheel to install all of our required packages from <a href="https://github.com/mikeyerm/ERM/blob/main/requirements.txt">requirements.txt</a>!<br>
Run this command inside of your venv to install setuptools/wheel: </p>
<pre><code>pip install --upgrade pip setuptools wheel</code></pre>
<p align="center">And finally, to download all of our packages:</p>
<pre><code>pip install -r requirements.txt</code></pre>
<p align="center"><i>If you made your venv outside of the ERM-main folder, you may have to run <code>pip install -r /ERM-main/requirements.txt</code> instead.</i></p>

<h2 id="ubuntu-debian-env-config" align="center">Environment Configuration (<code>.env</code> Setup)</h2>
<p align="center">Congrats on making it past that stage! Now, your .env file must be configured to include things such as your Discord Bot Token, MongoDB Atlas URI, API keys, and more. Your <code>.env</code> file should be in your ERM-main folder, but might be hidden from your file manager. To view the <code>.env</code> file, you can open the ERM-main folder in a code editor, such as Visual Studio Code, and edit the text. The following steps will be explained to fill out the .env file.
<br>
<b>Required for bot to function:</b></p>
<ul>
	<li>MongoDB Atlas URI</li>
	<li>Discord Bot Token</li>
	<li>Environment Type</li>
	<li>Custom Guild ID</li>
	<li>Panel API URL</li>
	<li>Sentry URL (Not <b>required</b> for bot to run, but recommended for error logging)</li>
</ul>

<h3 align="center">MongoDB Atlas URI</h3>
<p align="center">To get your <code>MONGO_URL</code>, you need to make a free MongoDB Atlas URI. <br>To do so, you need to <a href="https://www.mongodb.com/cloud/atlas/register">make an account with MongoDB</a> — it's free, and doesn't need a credit card. 
You can sign in with GitHub or Google, or just use your email. 
Once you have completed the sign-up process, you need to create a cluster. 
You should be able to do this by pressing the "Create Cluster" button. 
The Name, Provider and Region do not matter, simply press "Create Deployment" and wait for it to finish creating the cluster.
You should have gotten a popup asking you to connect to your cluster, and to make a database user, just press "create database user". 
To connect to your application, press the "Drivers" option, and copy the connection string. 
<br><b>Make sure to store this somewhere you will be able to access it from again</b>.
<br> Once done, go to "Network Access" on the sidebar, press "Add IP Address", click "Allow access from anywhere", and hit "Confirm".
 Paste the connecton string into the .env file after <code>MONGO_URL=</code>. 
<br>That should look like so, with your username, password and cluster name:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority
</code></pre>

<h3 align="center">Environment Type & Discord Bot Token</h3>
<p align="center">Next, we will change the Environment Type to <b>Custom</b>. Your ENVIRONMENT in your <code>.env</code> file should look like so:
<pre><code>ENVIRONMENT=CUSTOM</code></pre>
<br> 
<p align="center">To get your discord Bot Token, you need to create an application in the <a href="https://discord.com/developers/applications">Discord Developer Portal</a>.
Once you have a bot token, you need to add another line into your <code>.env</code> file. Since our environment type is <code>CUSTOM</code>, we can't use <code>PRODUCTION_BOT_TOKEN</code> or <codE>DEVELOPMENT_BOT_TOKEN</codE></p>Add a line anywhere, and type <code>CUSTOM_BOT_TOKEN=</code>. Paste your bot token after that. <br>
<br>
So far, your <code>.env</code> file should look like this: 
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL= <br>
PRODUCTION_BOT_TOKEN= <br>
DEVELOPMENT_BOT_TOKEN= <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
BLOXLINK_API_KEY=</code></pre>
<br>

<h3 align="center">Sentry Logging and Bloxlink API</h3>
<p align="center"><i>The following are not <b>required</b>, but some features might not work without a bloxlink API key.</i></p>
<p align="center">You do not need to fill out <code>PRODUCTION_BOT_TOKEN</code> or <code>DEVELOPMENT_BOT_TOKEN</code> if you have <code>ENVIRONMENT=CUSTOM</code> and <code>CUSTOM_BOT_TOKEN</code>. 
Unless you have a bloxlink API Key (which you can get from <a href="https://blox.link/dashboard/user/developer">here</a>), you do not need to fill it out. If you want error logging with Sentry, <a href="https://sentry.io/signup/">sign up here</a>, <b>Install Sentry</b>, select Python(vanilla) as the platform you want to monitor, press <b>configure SDK</b> (sentry-sdk has already been installed, you do not need to install it with pip again), and copy the URL in <code>dsn="yoursentrysdkurl"</code>. You need to edit <code>SENTRY_URL=</code> to <code>SENTRY_BASE_URL</code>, and then you can paste it into your <code>.env</code> file. <br>
<br> Your <code>.env</code> file should be looking like this:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL=yoursentrysdkurl <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
BLOXLINK_API_KEY=yourbloxlinkapikey</code></pre>

<h3 align="center">Custom Guild ID and Panel API URL</h3>
<p align="center">The following fields need to be added to your <code>.env</code> file for your bot to be able to function. <br></p>
<pre><code>CUSTOM_GUILD_ID=yourserverid <br>
PANEL_API_URL=[leave blank]</code></pre>
<p align="center">Your <code>.env</code> file should look like this now:
<pre><code>MONGO_URL=mongodb+srv://username:password@cluster-name.mongodb.net/?retryWrites=true&w=majority <br> 
ENVIRONMENT=CUSTOM <br>
SENTRY_URL=your://sentry.io.url/ <br>
CUSTOM_BOT_TOKEN=yourdiscordbottoken <br>
CUSTOM_GUILD_ID=yourserverid <br>
BLOXLINK_API_KEY=yourbloxlinkapikey <br>
PANEL_API_URL= [leave blank]</code></pre>
<p align="center">You can now save your <code>.env</code> file, and move onto the next step. That is everything that is required for your bot to host, everything else is just external APIs for er:lc, maple county, google sheets, etc. <br>
<b>Note: Make sure your file is saved as <code>.env</code>, not <code>.env.template</code> or something like <code>.env.txt</code>.</b></p>

<h2 id="ubuntu-debian-final-setup-running" align="center">Final Bot Setup and Running</h2>
<p align="center"> Once you have completed all previous steps, it is time to run your bot. This has to be done inside of the Virtual Environment we created — if you are no longer in that terminal, run the following commands:
<pre><code>cd ~/path/to/ERM-main<br>
python3 -m venv venv <br>
source venv/bin/activate </code></pre>
<p align="center">If your terminal has changed from this format: </p>
<pre><code>username@computername:~$</code></pre>
<p align="center"> to this: </p>
<pre><code>(venv) username@computername:~/path/to/ERM-main$ </code></pre>
<p align="center">You should be able to run the following command, which should start up your bot:</p>
<pre><code>python3 main.py</code></pre>
<p align="center">Well done! Your bot should now be running! If you close your terminal, or turn off your computer, your bot <b>will stop running</b>. If you want to safely stop the bot from running, press <code>Ctrl + C</code> inside of the terminal.
