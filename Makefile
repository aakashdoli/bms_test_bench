# Build the BMS controller as a shared library and run the C unit tests.
CFLAGS = -std=c11 -Wall -Wextra -Werror -pedantic -O2 -fPIC

# Detect the OS: macOS needs .dylib, Linux uses .so
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
  LIB     = build/libbms.dylib
  LIBFLAG = -dynamiclib
else
  LIB     = build/libbms.so
  LIBFLAG = -shared
endif

all: $(LIB)

$(LIB): firmware/bms.c firmware/bms.h
	@mkdir -p build
	$(CC) $(CFLAGS) $(LIBFLAG) -o $@ firmware/bms.c

build/test_bms: firmware/test_bms.c firmware/bms.c firmware/bms.h
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ firmware/test_bms.c firmware/bms.c

test: build/test_bms
	./build/test_bms

clean:
	rm -rf build

.PHONY: all test clean
