#include <stdio.h>
#include <stdlib.h>

#include "dload.h"

char * program_name;

void usage (int status) {
	printf("Usage: %s [URL]...\n", program_name);
	fputs("\
	Downloads and indexes man pages from Arch Linux packages.\n", stdout);
	fputs("\
	-a, --all                  do not ignore entries starting with .\n\
	-A, --almost-all           do not list implied . and ..\n\
	--author               with -l, print the author of each file\n\
	-b, --escape               print C-style escapes for nongraphic characters\n", stdout);
}

int main(int argc, char *argv[]) {
	program_name = argv[0];
//	usage(0);

	FILE *tmpfile;

	tmpfile = fopen("test.html", "wb");
	char *url = "https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.15.10.tar.xz";

	dload_payload test_payload;
	test_payload.fileurl = url;
	test_payload.content_disp_name = "hi";
	test_payload.localf = tmpfile;

	curl_download(&test_payload);

	fclose(tmpfile);

	return EXIT_SUCCESS;
}
