# Corgos Telgram BOT
## Free delivery of cute corgis images

### Background
I like corgis. Like, a lot. Sadly I cannot adopt one right now on in the near future, so I made the most reasonable thing a person could do:
I made a Telegram Bot that sends me a corgi picture whenever I want, like any sane person.

The bot is coded in Python by using the [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) library in order to interface with the official [Telegram api](https://core.telegram.org/)

### Usage
The bot it's pretty straightforward to use. Just start a conversation with \@corgos_bot or navigate to t.me/corgos_bot to start using it.
Usage of the commands:
* */start* will give you a brief description of the bot.
* */corgo* will send you a corgi picture.
* */goldencorgo* will tell you the tale of the Golden Corgo.
* */stats* will tell you some (mostly useless) information about the bot.

It will also reply to private messages, although not in a really smart way. I mean, it's a corgi, not a human.

**Video example:**

![demo - i cannot center this image :()](https://media.giphy.com/media/STxn673gNkyXwQXr1w/giphy.gif)

*(thanks to Reddit user u/GleamTheCube for his unwitting help. What a lovely corgi!)*

### Image sourcing
All the images are sourced from Reddit, namely from */r/corgi* and */r/babycorgis* subreddits. I do not own nor I choose any of this pictures. <br>
In order to be chosen, a post must have a minimum score, fixed in the settings file. I trust each moderator and their ability to remove any unsuitable image. <br>
The subreddits are scraped three times a week, at 2.20 AM (GMT), and every time about 250 photos are loaded (this might not be a fixed value).

### Next features
As I write this readme, the bot has been going for almost 9 month and about 20000 pictures have been sent.
I feel that, during the multiple iterations of this script (none of those are on GitHub, I'm sorry) I implemented every aspect I liked (and needed).
However, I plan to add one command to get photos of my corgi as soon as I manage to adopt one. Did I already mention that I love corgis?


## Installation
I provided a requirements.txt file in order to automatically install all the needed requirements. <br>
If you want to run this bot yourself on your machine, you have to follow a few steps:
1. Register to Reddit Api
2. Create a Telegram bot using \@botfather on Telegram and set the command list as it's provided in the code (line 145)
3. Create your own Golden Corgo image (yeah, I'm not going to provide it. That's top secret)
4. Fill the *settings.json* with the data you have gathered so far (Reddit access details, Telegram token)
5. Install all the requirements via the command `pip3 install -r requirements.txt`
6. Finally, run the script with `python3 corgos_bot.py`. The script will log everything in a file (named *logging.log*) in the same folder.

There you go! Your very own corgi-spamming-machine is up and running!

## Licensing
I provide the code under the *Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)* as it is also stated in the code.

I every picture belongs to their rightfully owner. I do not claim to own any of these.

## Additional infos
Now it's been a while since it started working and so far I have really been surprised by how many people have used this (pretty much useless, as I believe anyone will agree) bot.
I would never have expected it. Thank you all for your support!

I tried to comment the code as much as I could (sometimes too verbosly) and tried to keep the code as simple as I could, in order to make it legible for anyone who wanted to code a Telegram bot.
The code is PEP-8 compliant (not that it matters, I'm just so proud of it!). I wanted this feature to be mandatory since this is the first real Python project that I publish online.

This bot DOES NOT log any user or any group it's used by. As such, it can't (and it won't) ever send you or your group any message.
By coding this bot I discovered how much access a bot has to personal data, if either added to a group or messaged privately. ALWAYS BE CAREFUL ABOUT WHICH BOT YOU CHOOSE TO USE!

This bot is being currently hosted on a RaspberryPi 4 with 4GB of ram. It uses about 6% of the CPU and less than 1.5% of RAM while scraping pictures. While idling, the CPU usage drops to 0% and the RAM to about 1%.
(Data measured with *htop*)
