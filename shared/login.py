# (c) Copyright 2018 by Coinkite Inc. This file is part of Coldcard <coldcardwallet.com>
# and is covered by GPLv3 license found in COPYING.
#
# login.py - UX related to PIN code entry/login.
#
# NOTE: Mark3 hardware does not support secondary wallet concept.
#
import pincodes, version
from main import dis
from display import FontLarge, FontTiny
from uasyncio import sleep_ms
from ux import ux_press_release, ux_wait_keyup, ux_all_up, ux_poll_once, ux_show_story
from utils import pretty_delay
from callgate import show_logout

MAX_PIN_PART_LEN = 6
MIN_PIN_PART_LEN = 2

class LoginUX:

    def __init__(self):
        self.is_setting = False
        self.is_repeat = False
        self.subtitle = False
        self.offer_second = not version.has_608
        self.reset()

    def reset(self):
        self.pin = ''       # just the part we're showing
        self.pin_prefix = None
        self.words_ok = False
        self.is_secondary = False
        self.footer = None

    def show_pin(self, show_hint=False):
        filled = len(self.pin)
        if show_hint:
            filled -= 1
            hint = self.pin[-1] if not version.has_membrane else None

        dis.clear()

        if not self.pin_prefix:
            prompt="Enter PIN Prefix" 
        else:
            prompt="Enter rest of PIN" 


        if self.subtitle:
            dis.text(None, 0, self.subtitle)
            dis.text(None, 16, prompt, FontTiny)
        else:
            dis.text(None, 4, prompt)

        y = 26
        w = 18
        x = 12

        for idx in range(filled):
            dis.icon(x, y, 'xbox')
            x += w

        if show_hint:
            if not version.has_membrane:
                dis.text(x+1, y+1, hint, FontLarge)
                dis.icon(x, y, 'box')
            else:
                dis.icon(x, y, 'tbox')
        else:
            if len(self.pin) != MAX_PIN_PART_LEN:
                dis.icon(x, y, 'box')

        # BTW: √ also works here, but looks like square root, not a checkmark
        if self.footer:
            footer = self.footer
        elif self.is_repeat:
            footer = "CONFIRM PIN VALUE"
        elif not self.pin_prefix:
            footer = "X to CANCEL, or OK when DONE"
        else:
            footer = "X to CANCEL, or OK to CONTINUE"

        dis.text(None, -1, footer, FontTiny)

        dis.show()

    def _show_words(self, has_secondary=False):

        dis.clear()
        dis.text(None, 0, "Recognize these?" if (not self.is_setting) or self.is_repeat \
                            else "Write these down:")

        dis.show()
        dis.busy_bar(True)
        words = pincodes.PinAttempt.prefix_words(self.pin.encode())

        y = 15
        x = 18
        dis.text(x, y,    words[0], FontLarge)
        dis.text(x, y+18, words[1], FontLarge)

        if self.offer_second:
            dis.text(None, -1, "Press (2) for secondary wallet", FontTiny)
        else:
            dis.text(None, -1, "X to CANCEL, or OK to CONTINUE", FontTiny)

        dis.busy_bar(False)     # includes a dis.show()
        #dis.show()

    def cancel(self):
        self.reset()
        self.show_pin()
            

    def interact(self):
        # Prompt for prefix and pin. Returns string or None if the abort.

        self.show_pin()
        while 1:

            ch = await ux_press_release()
            if ch == 'x':
                if not self.pin and self.pin_prefix:
                    # cancel on empty 2nd-stage: start over
                    self.reset()
                    self.show_pin()
                    continue

                if not self.pin and not self.pin_prefix:
                    # X on blank first screen: stop
                    return None
                    
                # do a delete-one
                if self.pin:
                    self.pin = self.pin[:-1]
                    self.show_pin()

            elif ch == 'y':
                if len(self.pin) < MIN_PIN_PART_LEN:
                    # they haven't given enough yet
                    continue

                if self.pin_prefix:
                    # done!
                    return (self.pin_prefix + '-' + self.pin)

                self._show_words()

                nxt = await ux_wait_keyup('xy2' if self.offer_second else 'xy')
                if nxt == 'y' or nxt == '2':
                    self.pin_prefix = self.pin
                    self.pin = ''
                    self.is_secondary = (nxt == '2')
                elif nxt == 'x':
                    self.reset()

                self.show_pin()

                continue

            else:
                assert ch in '0123456789' or ch == ''

                if len(self.pin) == MAX_PIN_PART_LEN:
                    self.pin = self.pin[:-1] + ch
                else:
                    self.pin += ch

                self.show_pin(show_hint=True)

                await ux_all_up()

                self.show_pin(show_hint=False)

    async def do_delay(self, pa):
        # show # of failures and implement the delay, which could be 
        # very long.
        from main import numpad

        dis.clear()
        dis.text(None, 0, "Checking...", FontLarge)
        dis.text(None, 24, 'Wait '+pretty_delay(pa.delay_required * pa.seconds_per_tick))
        dis.text(None, 40, "(%d failures)" % pa.num_fails)

        # save a little bit of interrupt load/overhead
        numpad.stop()

        while pa.is_delay_needed():
            dis.progress_bar(pa.delay_achieved / pa.delay_required)
            dis.show()

            pa.delay()

        numpad.start()

    async def we_are_ewaste(self, num_fails):
        msg = '''After %d failed PIN attempts this Coldcard is locked forever. \
By design, there is no way to reset or recover the secure element, and its contents \
are now forever inaccessible.

Restore your seed words onto a new Coldcard.''' % num_fails

        while 1:
            ch = await ux_show_story(msg, title='I Am Brick!', escape='6')
            if ch == '6': break

    async def confirm_attempt(self, attempts_left, num_fails, value):

        ch = await ux_show_story('''You have %d attempts left before this Coldcard BRICKS \
ITSELF FOREVER.

Check and double-check your entry:\n\n  %s\n
Maybe even take a break and come back later.\n
Press OK to continue, X to stop for now.
''' % (attempts_left, value), title="WARNING")

        if ch == 'x':
            show_logout()
            # no return
        

    async def try_login(self, retry=True):
        from main import pa, numpad

        while retry:
            if version.has_608 and not pa.attempts_left:
                # tell them it's futile
                await self.we_are_ewaste(pa.num_fails)

            self.reset()

            if pa.num_fails:
                self.footer = '%d failures' % pa.num_fails
                if version.has_608:
                    self.footer += ', %d tries left' % pa.attempts_left

            pin = await self.interact()

            if pin is None:
                # Perhaps they are having trouble with touch pad?
                numpad.sensitivity = 2
                continue
            
            pa.setup(pin, self.is_secondary)

            if version.has_608 and pa.num_fails > 3:
                # they are approaching brickage, so warn them each attempt
                await self.confirm_attempt(pa.attempts_left, pa.num_fails, pin)
            elif pa.is_delay_needed():
                # mark 1/2 might come here, never mark3
                await self.do_delay(pa)

            # do the actual login attempt now
            dis.fullscreen("Wait...")
            try:
                dis.busy_bar(True)
                ok = pa.login()
                if ok: break        # success, leave
            except RuntimeError as exc:
                # I'm a brick and other stuff can happen here
                ok = False
                if exc.args[0] == pincodes.EPIN_I_AM_BRICK:
                    await self.we_are_ewaste(pa.num_fails)
                    continue
                else:
                    print("pa.login: %r" % exc)
            finally:
                dis.busy_bar(False)

            pa.num_fails += 1
            if version.has_608:
                pa.attempts_left -= 1

            msg = ""
            nf = '1 failure' if pa.num_fails <= 1 else ('%d failures' % pa.num_fails)
            if version.has_608:
                if not pa.attempts_left:
                    await self.we_are_ewaste(pa.num_fails)
                    continue

                msg += '%d attempts left' % (pa.attempts_left)
            else:
                msg += '%s' % nf

            msg += '''\n\nPlease check all digits carefully, and that prefix versus \
suffix break point is correct.'''
            if version.has_608:
                msg += '\n\n' + nf

            await ux_show_story(msg, title='WRONG PIN')

    async def prompt_pin(self):
        # ask for an existing PIN
        self.reset()
        return await self.interact()
            

    async def get_new_pin(self, title, story=None, allow_clear=False):
        # Do UX flow to get new (or change) PIN. Always does the double-entry thing
        self.is_setting = True
        self.offer_second = False

        if story:
            # give them background
            ch = await ux_show_story(story, title=title)

            if ch == 'x': return None

        # first first one
        first_pin = await self.interact()
        if first_pin is None: return None

        if allow_clear and first_pin == '999999-999999':
            # don't make them repeat the 'clear pin' value
            return first_pin

        self.is_repeat = True

        while 1:
            self.reset()
            second_pin = await self.interact()
            if first_pin is None: return None

            if first_pin == second_pin:
                return first_pin

            ch = await ux_show_story('''\
You gave two different PIN codes and they don't match.

Press 2 to try the second one again, X or OK to give up for now.''',
                        title="PIN Mismatch", escape='2')

            if ch != '2':
                return None




# EOF
