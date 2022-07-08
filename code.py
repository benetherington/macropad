#autocopy

from adafruit_display_text                  import label
import adafruit_ds3231
from adafruit_fancyled.adafruit_fancyled    import expand_gradient, CRGB, denormalize
from adafruit_hid.keyboard                  import Keyboard
from adafruit_hid.keycode                   import Keycode as K
import board
from digitalio                              import DigitalInOut, Pull
import keypad
import neopixel
import rotaryio
from terminalio                             import FONT
from time                                   import monotonic, struct_time
import usb_hid
from math import copysign


""" CLOCK """
rtc = adafruit_ds3231.DS3231(board.I2C())
print(rtc.datetime)

class Clock():
    INTERVAL = 30
    def __init__(self):
        self.d = board.DISPLAY
        self.d.rotation = 90
        
        self.l = label.Label(FONT, text="20\n15", scale=4)
        self.l.x = 10
        self.l.y = 25
        self.d.show(self.l)
        
        self.last_update = monotonic()-self.INTERVAL
        self.tick()

    def tick(self):
        if self.last_update+self.INTERVAL < monotonic():
            t = rtc.datetime
            hour = (t.tm_hour+1)%24
            self.l.text = f"{hour:0>2}\n{t.tm_min:0>2}"
clock = Clock()

""" KEYPAD """
# key_pins_portrait = (
#             board.KEY1,  board.KEY2,  board.KEY3,
#             board.KEY4,  board.KEY5,  board.KEY6,
#             board.KEY7,  board.KEY8,  board.KEY9,
#             board.KEY10, board.KEY11, board.KEY12)
key_pins_landscape = (
            board.KEY3, board.KEY6, board.KEY9, board.KEY12,
            board.KEY2, board.KEY5, board.KEY8, board.KEY11,
            board.KEY1, board.KEY4, board.KEY7, board.KEY10
)
keys = keypad.Keys(key_pins_landscape, value_when_pressed=False, pull=True)


""" OTHER IO """
encoder = rotaryio.IncrementalEncoder(board.ROTA, board.ROTB)
button = DigitalInOut(board.BUTTON)
button.switch_to_input(pull=Pull.UP)
pixel_buf = neopixel.NeoPixel(board.NEOPIXEL, 12, brightness=0.1)
pixels_rotated = (
    2, 5, 8, 11,
    1, 4, 7, 10,
    0, 3, 6, 9
)


""" HID """
class Voicemeeter():
    """
    A small class to handle mute and unmute states.
    """
    MUTE        = (K.ALT, K.F5) # alt + F5
    UNMUTE      = (K.ALT, K.F6) # alt + F6
    VOLUME_UP   = (K.ALT, K.F7)
    VOLUME_DOWN = (K.ALT, K.F8)
    def __init__(self, hid_device):
        self._hid_device = hid_device
        self.mute()
    @property
    def unmuted(self):
        return not self._muted
    @property
    def muted(self):
        return self._muted
    @muted.setter
    def muted(self, value):
        if value:
            self._hid_device.send(*self.MUTE)
            self._muted = True
        else:
            self._hid_device.send(*self.UNMUTE)
            self._muted = False
    def mute(self):
        self.muted = True
    def unmute(self):
        self.muted = False
    def toggle(self):
        self.muted = not self.muted
    def change_volume(self, change):
        direction = int(copysign(1, change))
        keycombo = (
            None,            # 0
            self.VOLUME_UP,  # 1
            self.VOLUME_DOWN # -1
        )[direction]
        count = abs(change)
        for _ in range(count):
            self._hid_device.send(*keycombo)

class MacroKeys():
    """
    The heavy lifter. It takes input (via key presses and Voicemeeter.muted
    state) and turns it into HID commands and neopixel colors.
    """
    # configure how often to update pixel colors
    FRAME_LENGTH = 0.1
    # Configure state and ripple colors: a longer gradient will result in a
    # "slower" animation. The length of both gradients should be the same, or
    # you might have issues when jumping from the longer one to the shorter one.
    # I haven't tested it, but it SHOULD be okay.
    MUTED_GRADIENT = expand_gradient(
        (
            (.60, CRGB( 237,  42,   7 )),
            (.80, CRGB( 255,  61,  94 )),
            (.90, CRGB( 199, 152,  22 )),
            (1.0, CRGB( 237,  42,   7 ))
        ), 50
    )
    UNMUTED_GRADIENT = expand_gradient(
        (
            (.60, CRGB(   0, 212, 123 )),
            (.80, CRGB(  64, 230,  81 )),
            (.90, CRGB(  31, 240, 222 )),
            (1.0, CRGB(   0, 212, 123 ))
        ), 50
    )
    RIPPLE_COLOR = CRGB(  82, 150,  14 )
    def __init__(self, keys, hid_device, pixel_buf, pixel_order):
        # deal with arguments
        self._keys = keys
        self._vm = Voicemeeter(hid_device)
        self._pixels = pixel_buf
        self._pixel_order = pixel_order

        # variable initial states
        self._last_frame_time = monotonic()
        self._ani_offset = 0
        self.pressed_keys = set()
        self.key_history = [frozenset()]*5
        self._timed_key_history = [[]]*5
        self._encoder_pos = encoder.position
    def tick(self):
        """
        Call this method repeatedly to drive button reactions and to animate LEDs.
        """
        self._handle_button_events()
        # self._set_brightness()
        self._set_volume()
        self._do_animate()
    def _set_volume(self):
        if not self._encoder_pos == encoder.position:
            delta = self._encoder_pos - encoder.position
            self._encoder_pos = encoder.position
            self._vm.change_volume(delta)
    def _set_brightness(self):
        if not self._encoder_pos == encoder.position:
            delta = self._encoder_pos - encoder.position
            self._encoder_pos = encoder.position
            self._pixels.brightness += delta*0.01
    def _do_animate(self):
        """
        Runs on an interval to update pixels. Take note! This is slower than
        _handle_button_events. It keeps track of its own color cycle progress
        (the _ani_offset variable), and also advances the _timed_key_history
        queue (used by _get_press_ripple_frame).
        """
        next_frame_time = self._last_frame_time + self.FRAME_LENGTH
        if next_frame_time > monotonic():
            # it's not time to perform an animation
            return
        # reset frame timer
        self._last_frame_time = monotonic()
        # Get base colors. If you want a ripple color that isn't static, use
        # _get_color_pressed instead.
        if self._vm.unmuted:
            base_palete = self.UNMUTED_GRADIENT
            # ripple_palete = self.UNMUTED_GRADIENT
        else:
            base_palete = self.MUTED_GRADIENT
            # ripple_palete = self.MUTED_GRADIENT
        base_colors = self._get_color_base(base_palete)
        ripple_color = self.RIPPLE_COLOR
        # ripple_color = self._get_color_pressed(pressed_palete)
        # Draw the ripple. You could also only set the pressed button color and
        # get rid of the ripple effect.
        for idx, color_emphasis in enumerate(self._get_press_ripple_frame()):
            if color_emphasis:
                base_colors[idx] = ripple_color
        # Update neopixels. We have to use _pixel_order since the Macropad is
        # rotated.
        for color_idx, pixel_idx in enumerate(self._pixel_order):
            self._pixels[pixel_idx] = denormalize(base_colors[color_idx])
        # advance animation timing
        self._ani_offset += 1
        self._ani_offset %= len(base_palete)
        # advance button history
        if self._ani_offset %2:
            # only updating every other frame gives us a slower animation
            self._timed_key_history.pop()
            self._timed_key_history.insert(0,[])
    
    """ COLORS """
    def _get_color_base(self, palete):
        """
        Loops through a palete. When _ani_offset is within 12 positions of the
        end of the palete, we need to also grab colors from the beginning. This
        could also be done with animation.colorcycle in the
        adafruit_led_animation library, but we want more control so that we can
        add ripple effects.
        """
        # Find the start and end positions for this animation offset. Divmod is
        # handy here, because it'll tell us if we went off the end of the
        # palete.
        start     = self._ani_offset % len(palete)
        wrap, end = divmod(self._ani_offset+12, len(palete))
        # get colors
        if wrap:
            base_colors = palete[start:] + palete[:end]
        else:
            base_colors = palete[start:end]
        return base_colors
    def _get_color_pressed(self, palete):
        """
        Currently unused. Un-comment code in _do_animate if you want the ripple
        color to cycle, instead of being satic.
        """
        # grab a single color from the palete
        base_color = palete[self._ani_offset]
        # make it a bit brighter
        return [
            v+0.2
            for v in base_color
        ]
    def _get_press_ripple_frame(self):
        """
        Uses masks to determine color alterations for rippling button press
        effects. Instead of calculating which pixels have a ripple using an
        expanding radius and a lot of math, it's faster and more fun to use
        sprites! You could add additional animation frames (if you also add more
        empty history frames to _timed_key_history in __init__), and create
        fancier ripple patterns. Maybe they should sparkle?
        
        Each mask is oversized, allowing for margins around the 4x3
        grid of buttons. If we were to drop the leftmost columns and bottommost
        rows, the center of this mask would be placed in the bottom left corner.
        We'll pick which rows and columns to drop based on the YX location of
        the button pushed, placing the center of the mask where we want it.
        Luckily, buttons are indexed by zero, resulting in a very clean use of
        divmod to get (y, x). Note that we already set the buttons in a
        landscape orientation when we instantiated keypad.Keys.

           INDEXED                DIVMOD'D YX
        --------------      ----------------------
        | 0  1  2  3 |      | 0,0  0,1  0,2  0,3 |
        | 4  5  6  7 |  =>  | 1,0  1,1  1,2  1,3 |
        | 8  9 10 11 |      | 2,0  2,1  2,2  2,3 |
        --------------      ----------------------

        Since each mask's center is at (2,3), button 0 requires dropping out two
        rows from the top and three columns from the left. Button 4 needs one
        row dropped from the top, and one from the bottom.

        divmod(0) = 0,0  =>  drop_from_top:2, bottom:0, right:0, left:3
        divmod(4) = 1,0  =>  drop_from_top:1, bottom:1, right:0, left:3

        This could be calculated as:
        
        drop_from_top    = 2 - y
        drop_from_bottom = 2 - drop_from_top
        drop_from_left   = 3 - x
        drop_from_right  = 3 - drop_from_left
        
        ... but it's more useful to use slices instead so we can grab the rows
        and columns we want in a single step:

        divmod(0)  = 0,0  =>  column_start:2, end:5, row_start:3, end:7
        divmod(1)  = 0,1  =>  column_start:2, end:5, row_start:2, end:6
        divmod(4)  = 1,0  =>  column_start:1, end:4, row_start:3, end:7
        divmod(11) = 2,3  =>  column_start:0, end:3, row_start:0, end:4

        This turns out to be even simpler to calculate:

        column_start = 2 - y
        column_end   = 5 - y
        row_start    = 3 - x
        row_end      = 7 - x

        """
        # Go through each history state and create a mask for the keys pressed
        # at that state. Ripples created farther back in history have bigger
        # circles now.
        masks = []
        for button in self._timed_key_history[0]:
            # most recent history state
            mask = [[0,0,0,0,0,0,0],
                    [0,0,0,1,0,0,0],
                    [0,0,1,0,1,0,0],
                    [0,0,0,1,0,0,0],
                    [0,0,0,0,0,0,0]]
            y, x = divmod(button,4)
            col_start = 2 - y
            col_end   = 5 - y
            row_start = 3 - x
            row_end   = 7 - x
            trimmed = [
                row[row_start:row_end]
                for row
                in mask[col_start:col_end]
            ]
            masks.append(trimmed)
        for button in self._timed_key_history[1]:
            # second history state
            mask = [[0,0,0,1,0,0,0],
                    [0,0,1,0,1,0,0],
                    [0,1,0,0,0,1,0],
                    [0,0,1,0,1,0,0],
                    [0,0,0,1,0,0,0]]
            y, x = divmod(button,4)
            col_start = 2 - y
            col_end   = 5 - y
            row_start = 3 - x
            row_end   = 7 - x
            trimmed = [
                row[row_start:row_end]
                for row
                in mask[col_start:col_end]
            ]
            masks.append(trimmed)
        for button in self._timed_key_history[2]:
            # third history state
            mask = [[0,0,1,0,1,0,0],
                    [0,1,0,0,0,1,0],
                    [1,0,0,0,0,0,1],
                    [0,1,0,0,0,1,0],
                    [0,0,1,0,1,0,0]]
            y, x = divmod(button,4)
            col_start = 2 - y
            col_end   = 5 - y
            row_start = 3 - x
            row_end   = 7 - x
            trimmed = [
                row[row_start:row_end]
                for row
                in mask[col_start:col_end]
            ]
            masks.append(trimmed)
        for button in self._timed_key_history[3]:
            # fourth history state
            mask = [[0,1,0,0,0,1,0],
                    [1,0,0,0,0,0,1],
                    [0,0,0,0,0,0,0],
                    [1,0,0,0,0,0,1],
                    [0,1,0,0,0,1,0]]
            y, x = divmod(button,4)
            col_start = 2 - y
            col_end   = 5 - y
            row_start = 3 - x
            row_end   = 7 - x
            trimmed = [
                row[row_start:row_end]
                for row
                in mask[col_start:col_end]
            ]
            masks.append(trimmed)
        # Sum each pixel position. Ripple intersections could be made brighter
        # in _do_animate because we're handing back sums instead of just
        # true/false values.
        summed_mask = []
        for row in zip(*masks):
            # note that zip(*[]) is the inverse of zip([])
            columns = zip(*row)
            summed_row = list( map(sum, columns) )
            summed_mask.append(summed_row)
        # return a flat list
        if not summed_mask:
            # if all history states are empty, no masks will have been created
            return [0]*4*3
        return summed_mask[0] + summed_mask[1] + summed_mask[2]


    """ BUTTONS AND HISTORY """
    def _handle_button_events(self):
        """
        Sends vm toggle commands on button presses and releases unless a rocker gesture was
        performed.
        """
        event = self._update_event_history()
        if not event:
            return
        if self._recognize_rocker():
            return
        elif self._recognize_toggle():
            self._vm.toggle()
    def _update_event_history(self):
        """
        Runs as often as possible to react to key events. We store information
        from events in three places:
        
        -- pressed_keys: this is a set of all currently pressed key numbers. We add to
        the set when new keys are pressed, and remove when they're released.
        Because this is a set (and not a list), it will only store unique
        values. That shouldn't be important because keypad.Keys uses an event
        queue, but I always treat state trackers with distrust.
        -- key_history: this is how we remember what previous pressed_keys sets
        looked like. We only need to remember a history long enough to look for
        gestures. pop() and insert(0,) let this list act like a queue. We add to
        the front and remove from the back, so that the first items are more
        recent than the last ones.
        -- _timed_key_history: this is just like key_history, but we don't
        pop and insert items. Instead, we add key presses to the first history
        list, and let _do_animate remove history states once per animation
        cycle. If more than one key is pressed in a single animation cycle, the
        key numbers will "pile up" and their ripples will all get animated at
        the same time.
        """
        # get new event
        event = self._keys.events.get()
        if not event:
            # nothing to update!
            return
        # update pressed keys
        if event.pressed:
            self.pressed_keys.add(event.key_number)
            self._timed_key_history[0].append(event.key_number)
        else:
            self.pressed_keys.discard(event.key_number)
        # update key history
        self.key_history.pop()
        self.key_history.insert(0, frozenset(self.pressed_keys))
        return event
    
    """ GESTURES """
    def _recognize_rocker(self):
        """
        A rocking gesture, where one key is pressed, then a second, then they
        are released in the same order.

        This logic is super dense, but it's surprising how much work we can do
        in so few lines of code. First, we check the length of each key_history
        state. If we don't see the right pattern, we don't need to do any more
        work: it's not a rocking gesture. Maybe it was a single key
        press-release, maybe it was a bunch of keys mashed at once. After that,
        we can check the numbers of each key to confirm that it's a rocker
        gesture. Because key_history is a list of sets, we can use the < and >
        operators to check that they are proper subsets and supersets of each
        other. mid_state must contain all of the keys (ie the one key) in both
        new_state and old_state. Because we're using the proper superset/subset
        operators instead of <= and >=, we also know that the button in
        new_state is not in old_state. To be honest, I'm pretty sure you could
        use only one of these (history length vs super/subset checks) and it
        would still work just fine.

        This is the only implemented gesture. I've included three other methods
        that I thought would be helpful when I started coding, but turned out
        not to have any use for my project. Maybe they would make displaying
        information on the display easier? Maybe you could beep when a gesture
        has ended?
        """
        if not tuple(map(lambda s: len(s), self.key_history)) == (0,1,2,1,0):
            return
        _, new_state, mid_state, old_state, _ = self.key_history
        if new_state < mid_state > old_state:
            return True
    def _gesture_ended(self):
        # history states only ever change by one key
        return bool(
            len(self.key_history[0]) == 0
            and len(self.key_history[1]) == 1
        )
    def _gesture_started(self):
        return bool(
            len(self.key_history[0]) == 1
            and len(self.key_history[1]) == 0
        )
    def _recognize_toggle(self):
        # returns true if a solo or multi-button press has begun or ended
        last_two_historical_lengths = tuple(map(
            lambda s: len(s), self.key_history[0:2]
        ))
        # recognize start of toggle
        if last_two_historical_lengths == (1,0):
            return True
        # recognize end of toggle
        if last_two_historical_lengths == (0,1):
            return True
        # else additional keys were pressed


hid_kbd = Keyboard(usb_hid.devices)
macro_keys = MacroKeys(keys, hid_kbd, pixel_buf, pixels_rotated)



""" MAIN LOOP """
# clear event buffer
while keys.events.get():
    pass

if __name__ == "__main__":
    while True:
        macro_keys.tick()
        clock.tick()
