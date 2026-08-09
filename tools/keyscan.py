"""Every key event pygame sees, shown IN the window. Esc quits.

    python tools/keyscan.py
"""
import pygame

pygame.init()
screen = pygame.display.set_mode((720, 260))
pygame.display.set_caption("keyscan -- click me, then press keys")
font = pygame.font.SysFont("consolas", 16)
lines = ["click this window, then press keys"]


def show():
    screen.fill((10, 10, 30))
    for i, ln in enumerate(lines[-12:]):
        screen.blit(font.render(ln, True, (220, 220, 120)), (8, 6 + i * 20))
    pygame.display.flip()


def log(s):
    print(s, flush=True)
    lines.append(s)
    show()


show()
while True:
    ev = pygame.event.wait()
    if ev.type == pygame.QUIT:
        break
    if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
        log("%s name=%r key=%d scancode=%d mod=%04x"
            % ("DOWN" if ev.type == pygame.KEYDOWN else "UP",
               pygame.key.name(ev.key), ev.key,
               getattr(ev, "scancode", -1), ev.mod))
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            break
    elif ev.type == pygame.TEXTINPUT:
        log("TEXT %r" % ev.text)
    elif ev.type != pygame.MOUSEMOTION:
        log("EVENT %s focused=%s"
            % (pygame.event.event_name(ev.type), pygame.key.get_focused()))

pygame.quit()
