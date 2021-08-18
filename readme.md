# Voicemeeter PTT/cough button CircuitPython script for the [Adafruit Macropad RP2040](https://www.adafruit.com/product/5128)

I've been using hotkeys to mute and unmute my mic in [Voicemeeter](https://vb-audio.com/Voicemeeter/) for years, and it's been driving me a little nuts. The VM macrobuttons app is great, but there wasn't enough visual feedback for me. I was very excited to get a Macropad in this quarter's Adabox, because I knew exactly what to do with it.

This is a bit of quick code to turn the entire Macropad into a cough button. And a push-to-talk button. And a mute indicator. It's everything I need, all in one! When the script starts, it sends a mute keycombo to start off with my mic muted in Voicemeeter. Pressing any key unmutes my mic, and releasing the key mutes it again. That's the push-to-talk.

When my mic is muted, the keys light up red, with a gentle strobe effect. When it's unmuted, the keys light up blue. That's the visual feedback. It's easy to see in my peripheral vision, even if the Voicemeeter app is minimized or under another window. It's also very pretty, don't discount that. For some extra flare, there's also a ripple effect that radiates out from pressed buttons.

I don't always want to be in PTT mode! I was inspired by an unusual momentary switch I once saw, that locked in the on position when you slid the button sideways. You find this latch-on behavior in some power tools, like a router, but it involves two separate controls: a trigger to activate, then a separate button to lock. In any event, this script looks for a gesutre I've called a "rocker" motion. When any two buttons are pressed and released in a rocking motion (press #1, press #2, release #1, release #2), the Macropad switches into push-to-mute mode. That's the cough button.

It's pretty, it's functional, and it has a killer replica of Pioneer 10's gold plaque. And a Vera Ruben quote. And a diagram of Shuttle's abort mode switch. It's perfect for a space nerd with a podcast.

## DEPENDENCIES
From Adafruit sponsored libraries:

* [adafruit_fancyled](https://circuitpython.readthedocs.io/projects/fancyled/en/latest/)
* [adafruit_hid](https://circuitpython.readthedocs.io/projects/hid/en/latest/)

