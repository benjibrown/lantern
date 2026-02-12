import curses

def main(stdscr):

    curses.cbreak()
    stdscr.keypad(True)
    curses.noecho()
    


    # remove bg 
    curses.start_color() 
    curses.use_default_colors()
    stdscr.clear()
    stdscr.addstr(0, 0, "Press keys to see their values.")
    stdscr.addstr(1, 0, "Press 'q' to quit.")
    stdscr.refresh()

    row = 3

    while True:
        ch = stdscr.getch()

        # Quit on q
        if ch == ord('q'):
            break

        try:
            char_repr = repr(chr(ch))
        except:
            char_repr = "Non-printable"

        stdscr.addstr(row, 0, f"Key code: {ch:<5} | Char: {char_repr}      ")
        stdscr.refresh()

        row += 1

        # Prevent scrolling forever
        if row >= curses.LINES - 1:
            stdscr.clear()
            stdscr.addstr(0, 0, "Press keys to see their values.")
            stdscr.addstr(1, 0, "Press 'q' to quit.")
            row = 3

curses.wrapper(main)

