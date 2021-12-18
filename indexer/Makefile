.POSIX:

CC = gcc
CFLAGS = -Wall -lcurl -g

TARGET = indexer

all: $(TARGET)

indexer: clean
	$(CC) $(CFLAGS) -o $(TARGET) $(TARGET).c dload.c util.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
