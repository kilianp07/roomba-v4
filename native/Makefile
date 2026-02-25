# Detect OpenSSL location
OPENSSL_PREFIX := $(shell \
	brew --prefix openssl@3 2>/dev/null || \
	(test -d /usr/local/opt/openssl@3 && echo /usr/local/opt/openssl@3) || \
	(test -d /opt/homebrew/opt/openssl@3 && echo /opt/homebrew/opt/openssl@3) || \
	(pkg-config --variable=prefix openssl 2>/dev/null) || \
	echo /usr)

CC := cc
CFLAGS := -Wall -O2 -I$(OPENSSL_PREFIX)/include
LDFLAGS := -L$(OPENSSL_PREFIX)/lib -lssl -lcrypto

PREFIX ?= $(HOME)/.local

mqtt_bridge: mqtt_bridge.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

install: mqtt_bridge
	install -d $(PREFIX)/bin
	install -m 755 mqtt_bridge $(PREFIX)/bin/mqtt_bridge

clean:
	rm -f mqtt_bridge

.PHONY: clean install
