#include <stdio.h>
#include <stdlib.h>

#include "dload.h"

char * program_name;

void usage (int status) {
      printf("Usage: %s [OPTION]... [FILE]...\n", program_name);
      fputs("\
Downloads and indexes man pages from Arch Linux packages.\n\
", stdout);
      fputs("\
  -a, --all                  do not ignore entries starting with .\n\
  -A, --almost-all           do not list implied . and ..\n\
      --author               with -l, print the author of each file\n\
  -b, --escape               print C-style escapes for nongraphic characters\n\
", stdout);
}

int main(int argc, char *argv[]) {
	program_name = argv[0];
	usage(0);
	return EXIT_SUCCESS;
}
