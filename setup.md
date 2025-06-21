<p align="center">
  <img src="https://github.com/user-attachments/assets/2c466719-27cf-4b1f-9c4d-390306fb9ab6" alt="ERM Bot Logo">
</p>

<h1 align="center">🤖 Setup Your Own Instance</h1>

* ⚠️ **WARNING:** Whenever you want ERM to run, you must be running the program. 

* ℹ️It is reccomended to have a dedicated computer/server just to host programs. **Running on person machines is not reccomended.**


<h2 align="center">💉 Prerequisites</h2>

* Python (Reccomended Python 3.13)
  * Install On [The Official Python Website](https://www.python.org/downloads/)
* Finish Later

<h2 align="center">🔑 Clone the ERM repo</h2>

1. Open the [Official ERM Repository](https://github.com/mikeyerm/ERM) in a [modern web browser](https://www.mozilla.org/firefox) ([or this browser](https://brave.com/))
2. Download the code
   * Click on the blue `Code` button.
   * Click on Download ZIP near the bottom of the opened panel.
   * Unzip the downloaded file.



<h2 align="center">💽 Install Python Requirements</h2>

❗If you just installed python, a computer restart may be required!

1. Right Click on the `requirements.txt` file in the ERM folder.
2. Select `Copy Path` or `Copy as Path`
3. Open Command Prompt
    * Hold the windows key + the r key
    * Type in cmd.exe
    * Click `Run` or press the `enter` key
  
4. Type in the following command **(replace <paste> with the thing you copied)**
```cmd
python -m pip install -r <paste>
```
5. Press the `enter` key.

<h2 align="center">🔑 Setup .env</h2>

1. Open File Explorer in the ERM Folder
2. Duplicate the file named `.env.template` into another file named `.env`
3. Fill out the fields. **Certain fields will have documentation on how to fill out below.**
   
<h4 align="center">MONGO_URL</h2>

1. Create a MongoDB account ([signup page](https://www.mongodb.com/cloud/atlas/register))
2. Build a Cluster on the dashboard
3. Open the dashboard
4. Select Connect on the cluster you want to use
5. Select a user and password you want to use **(REMEMBER THIS)**
6. Click `Choose a Connection Method`
7. Select `Drivers`
8. Find the piece of code that says something like:

```
mongodb+srv://<db_user>:<db_password>@mycluster.<random>.mongodb.net/?retryWrites=true&w=majority&appName=<yourclustername>
```

9. Copy the part saying `srv://<db_user>:<db_password> etc.`
10. That is your MONGO_URL.

<h4 align="center">ENVIRONMENT</h2>

**PRODUCTION** or **DEVELOPMENT** *(if you dont know which to use, use PRODUCTION)*

<h4 align="center">SENTRY_URL</h2>
[How to Setup a Sentry App](https://www.youtube.com/watch?v=A64tezVRSK8)

*im not writing all this shit out*

<h4 align="center">BLOXLINK_API_KEY</h2>
Bloxlink API Key

