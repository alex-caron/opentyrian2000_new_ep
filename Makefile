# BUILD SETTINGS ###############################################################

ifneq ($(filter Msys Cygwin, $(shell uname -o)), )
    PLATFORM := WIN32
    TYRIAN_DIR = C:\\TYRIAN
else
    PLATFORM := UNIX
    TYRIAN_DIR = $(gamesdir)/opentyrian2000
endif

# The base game only requires SDL2.  SDL2_net support can be enabled with:
#     make WITH_NETWORK=true
WITH_NETWORK ?= false

################################################################################

# see https://www.gnu.org/prep/standards/html_node/Makefile-Conventions.html

SHELL = /bin/sh

CC ?= gcc
INSTALL ?= install
PKG_CONFIG ?= pkg-config
SDL2_CONFIG ?= sdl2-config

VCS_IDREV ?= (git describe --tags || git rev-parse --short HEAD)

INSTALL_PROGRAM ?= $(INSTALL)
INSTALL_DATA ?= $(INSTALL) -m 644

prefix ?= /usr/local
exec_prefix ?= $(prefix)

bindir ?= $(exec_prefix)/bin
datarootdir ?= $(prefix)/share
datadir ?= $(datarootdir)
docdir ?= $(datarootdir)/doc/opentyrian2000
mandir ?= $(datarootdir)/man
man6dir ?= $(mandir)/man6
man6ext ?= .6
desktopdir ?= $(datarootdir)/applications
icondir ?= $(datarootdir)/icons

# see https://www.pathname.com/fhs/pub/fhs-2.3.html

gamesdir ?= $(datadir)/games

###

TARGET := opentyrian2000

SRCS := $(wildcard src/*.c)
OBJS := $(SRCS:src/%.c=obj/%.o)
DEPS := $(SRCS:src/%.c=obj/%.d)

###

ifeq ($(WITH_NETWORK), true)
    EXTRA_CPPFLAGS += -DWITH_NETWORK
endif

OPENTYRIAN_VERSION := $(shell $(VCS_IDREV) 2>/dev/null && \
                              touch src/opentyrian_version.h)
ifneq ($(OPENTYRIAN_VERSION), )
    EXTRA_CPPFLAGS += -DOPENTYRIAN_VERSION='"$(OPENTYRIAN_VERSION)"'
endif

CPPFLAGS ?= -MMD
CPPFLAGS += -DNDEBUG
CFLAGS ?= -pedantic \
          -Wall \
          -Wextra \
          -Wno-missing-field-initializers \
          -O2
ifneq ($(findstring clang,$(shell $(CC) --version 2>/dev/null)),clang)
    CFLAGS += -Wno-format-truncation
endif
LDFLAGS ?=
LDLIBS ?=

PKG_CONFIG_FOUND := $(shell command -v $(PKG_CONFIG) 2>/dev/null)
SDL2_CONFIG_FOUND := $(shell command -v $(SDL2_CONFIG) 2>/dev/null)

ifeq ($(WITH_NETWORK), true)
    ifeq ($(PKG_CONFIG_FOUND), )
        $(error WITH_NETWORK=true requires pkg-config and SDL2_net; on macOS run: brew install pkgconf sdl2_net)
    endif
    SDL_CPPFLAGS := $(shell $(PKG_CONFIG) sdl2 SDL2_net --cflags)
    SDL_LDFLAGS := $(shell $(PKG_CONFIG) sdl2 SDL2_net --libs-only-L --libs-only-other)
    SDL_LDLIBS := $(shell $(PKG_CONFIG) sdl2 SDL2_net --libs-only-l)
else
    ifneq ($(PKG_CONFIG_FOUND), )
        SDL_CPPFLAGS := $(shell $(PKG_CONFIG) sdl2 --cflags)
        SDL_LDFLAGS := $(shell $(PKG_CONFIG) sdl2 --libs-only-L --libs-only-other)
        SDL_LDLIBS := $(shell $(PKG_CONFIG) sdl2 --libs-only-l)
    else
        ifneq ($(SDL2_CONFIG_FOUND), )
            SDL_CPPFLAGS := $(shell $(SDL2_CONFIG) --cflags)
            SDL_LDLIBS := $(shell $(SDL2_CONFIG) --libs)
        else
            $(error SDL2 was not found; on macOS run: brew install sdl2)
        endif
    endif
endif

ALL_CPPFLAGS = -DTARGET_$(PLATFORM) \
               -DTYRIAN_DIR='"$(TYRIAN_DIR)"' \
               $(EXTRA_CPPFLAGS) \
               $(SDL_CPPFLAGS) \
               $(CPPFLAGS)
ALL_CFLAGS = -std=iso9899:1999 \
             $(CFLAGS)
ALL_LDFLAGS = $(SDL_LDFLAGS) \
              $(LDFLAGS)
ALL_LDLIBS = -lm \
             $(SDL_LDLIBS) \
             $(LDLIBS)

###

.PHONY : all
all : $(TARGET)

.PHONY : debug
debug : CPPFLAGS += -UNDEBUG
debug : CFLAGS += -Werror
debug : CFLAGS += -O0
debug : CFLAGS += -g3
debug : all

.PHONY : installdirs
installdirs :
	mkdir -p $(DESTDIR)$(bindir)
	mkdir -p $(DESTDIR)$(docdir)
	mkdir -p $(DESTDIR)$(man6dir)
	mkdir -p $(DESTDIR)$(desktopdir)
	mkdir -p $(DESTDIR)$(icondir)/hicolor/22x22/apps
	mkdir -p $(DESTDIR)$(icondir)/hicolor/24x24/apps
	mkdir -p $(DESTDIR)$(icondir)/hicolor/32x32/apps
	mkdir -p $(DESTDIR)$(icondir)/hicolor/48x48/apps
	mkdir -p $(DESTDIR)$(icondir)/hicolor/128x128/apps

.PHONY : install
install : $(TARGET) installdirs
	$(INSTALL_PROGRAM) $(TARGET) $(DESTDIR)$(bindir)/
	$(INSTALL_DATA) NEWS README.md $(DESTDIR)$(docdir)/
	$(INSTALL_DATA) linux/man/opentyrian2000.6 $(DESTDIR)$(man6dir)/opentyrian2000$(man6ext)
	$(INSTALL_DATA) linux/opentyrian2000.desktop $(DESTDIR)$(desktopdir)/
	$(INSTALL_DATA) linux/icons/tyrian2000-22.png $(DESTDIR)$(icondir)/hicolor/22x22/apps/opentyrian2000.png
	$(INSTALL_DATA) linux/icons/tyrian2000-24.png $(DESTDIR)$(icondir)/hicolor/24x24/apps/opentyrian2000.png
	$(INSTALL_DATA) linux/icons/tyrian2000-32.png $(DESTDIR)$(icondir)/hicolor/32x32/apps/opentyrian2000.png
	$(INSTALL_DATA) linux/icons/tyrian2000-48.png $(DESTDIR)$(icondir)/hicolor/48x48/apps/opentyrian2000.png
	$(INSTALL_DATA) linux/icons/tyrian2000-128.png $(DESTDIR)$(icondir)/hicolor/128x128/apps/opentyrian2000.png

.PHONY : uninstall
uninstall :
	rm -f $(DESTDIR)$(bindir)/$(TARGET)
	rm -f $(DESTDIR)$(docdir)/NEWS $(DESTDIR)$(docdir)/README.md
	rm -f $(DESTDIR)$(man6dir)/opentyrian2000$(man6ext)
	rm -f $(DESTDIR)$(desktopdir)/opentyrian2000.desktop
	rm -f $(DESTDIR)$(icondir)/hicolor/22x22/apps/opentyrian2000.png
	rm -f $(DESTDIR)$(icondir)/hicolor/24x24/apps/opentyrian2000.png
	rm -f $(DESTDIR)$(icondir)/hicolor/32x32/apps/opentyrian2000.png
	rm -f $(DESTDIR)$(icondir)/hicolor/48x48/apps/opentyrian2000.png
	rm -f $(DESTDIR)$(icondir)/hicolor/128x128/apps/opentyrian2000.png

.PHONY : clean
clean :
	rm -f $(OBJS)
	rm -f $(DEPS)
	rm -f $(TARGET)

$(TARGET) : $(OBJS)
	$(CC) $(ALL_CFLAGS) $(ALL_LDFLAGS) -o $@ $^ $(ALL_LDLIBS)

-include $(DEPS)

obj/%.o : src/%.c
	@mkdir -p "$(dir $@)"
	$(CC) $(ALL_CPPFLAGS) $(ALL_CFLAGS) -c -o $@ $<
