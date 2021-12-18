#include <errno.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <string.h>

#define DIM(x) (sizeof(x)/sizeof(*(x)))

static int cached_columns = -1;


static int getcols_fd(int fd)
{
	int width = -1;

	if(!isatty(fd)) {
		return 0;
	}

#if defined(TIOCGSIZE)
	struct ttysize win;
	if(ioctl(fd, TIOCGSIZE, &win) == 0) {
		width = win.ts_cols;
	}
#elif defined(TIOCGWINSZ)
	struct winsize win;
	if(ioctl(fd, TIOCGWINSZ, &win) == 0) {
		width = win.ws_col;
	}
#endif

	if(width <= 0) {
		return -EIO;
	}

	return width;
}

unsigned short getcols(void)
{
	const char *e;
	int c = -1;

	if(cached_columns >= 0) {
		return cached_columns;
	}

	e = getenv("COLUMNS");
	if(e && *e) {
		char *p = NULL;
		c = strtol(e, &p, 10);
		if(*p != '\0') {
			c= -1;
		}
	}

	if(c < 0) {
		c = getcols_fd(STDOUT_FILENO);
	}

	if(c < 0) {
		c = 80;
	}

	cached_columns = c;
	return c;
}

/* calculateSize(size): convert bytes to human-readable string */

static const char     *sizes[]   = { "EiB", "PiB", "TiB", "GiB", "MiB", "KiB", "B" };
static const uint64_t  exbibytes = 1024ULL * 1024ULL * 1024ULL *
                                   1024ULL * 1024ULL * 1024ULL;

char * calculateSize(uint64_t size) {   
    char     *result = (char *) malloc(sizeof(char) * 20);
    uint64_t  multiplier = exbibytes;
    int i;

    for (i = 0; i < DIM(sizes); i++, multiplier /= 1024)
    {   
        if (size < multiplier)
            continue;
        if (size % multiplier == 0)
            sprintf(result, "%" PRIu64 " %s", size / multiplier, sizes[i]);
        else
            sprintf(result, "%.1f %s", (float) size / multiplier, sizes[i]);
        return result;
    }
    strcpy(result, "0");
    return result;
}

