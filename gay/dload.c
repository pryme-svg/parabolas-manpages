#include <curl/curl.h>
#include <curl/easy.h>
#include <stdio.h>
#include <string.h>

#include "util.h"
#include "dload.h"

static int dload_progress_cb(void *file, curl_off_t dltotal, curl_off_t dlnow, curl_off_t ultotal, curl_off_t ulnow) {

	dload_payload *payload = (dload_payload *)file;

	if (dltotal <= 0) {
		return 0;
	}

	double bar_percent = (dlnow * 1.0/dltotal) * 100;

	const unsigned short cols = getcols();
	int infolen = cols * 6 / 10;
	if (infolen < 50) {
		infolen = 50;
	}
	int proglen = cols - infolen;

	const int hashlen = proglen > 8 ? proglen - 8 : 0;
	const int hash = bar_percent * hashlen / 100;
	static int lasthash = 0, mouth = 0;
	int i;

	if(bar_percent == 0) {
		lasthash = 0;
		mouth = 0;
	}

	if(hashlen > 0) {
		fprintf(stdout, "%20s %4s %5s", payload->content_disp_name, calculateSize(dlnow), calculateSize(dltotal));
		fputs(" [", stdout);
		for(i = hashlen; i > 0; --i) {
			/* if special progress bar enabled */
			if(i > hashlen - hash) {
				putchar('-');
			} else if(i == hashlen - hash) {
				if(lasthash == hash) {
					if(mouth) {
						fputs("\033[1;33mC\033[m", stdout);
					} else {
						fputs("\033[1;33mc\033[m", stdout);
					}
				} else {
					lasthash = hash;
					mouth = mouth == 1 ? 0 : 1;
					if(mouth) {
						fputs("\033[1;33mC\033[m", stdout);
					} else {
						fputs("\033[1;33mc\033[m", stdout);
					}
				}
			} else if(i % 3 == 0) {
				fputs("\033[0;37mo\033[m", stdout);
			} else {
				fputs("\033[0;37m \033[m", stdout);
			}
			
		}
		putchar(']');
	}
	/* print display percent after progress bar */
	/* 5 = 1 space + 3 digits + 1 % */
	if(proglen >= 5) {
		printf(" %3d%%", (int)bar_percent);
	}

	putchar('\r');
	fflush(stdout);


	return 0;
}
	

static void curl_set_handle_opts(CURL *curl, dload_payload *payload) {
	curl_easy_reset(curl);
	curl_easy_setopt(curl, CURLOPT_USERAGENT, "Man page crawler (info@parabolas.xyz; https://man.parabolas.xyz/)");
	curl_easy_setopt(curl, CURLOPT_URL, payload->fileurl);

	if (payload->write_string == 0) {
		curl_easy_setopt(curl, CURLOPT_WRITEDATA, payload->dest_string);
		curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writefunc);
	} else {
		curl_easy_setopt(curl, CURLOPT_WRITEDATA, payload->localf);
	}

	curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, payload->error_buffer);
	curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
	curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 10L);
	curl_easy_setopt(curl, CURLOPT_FILETIME, 1L);
	curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
	curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
	curl_easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, dload_progress_cb);
	curl_easy_setopt(curl, CURLOPT_XFERINFODATA, (void *)payload);
	curl_easy_setopt(curl, CURLOPT_NETRC, CURL_NETRC_OPTIONAL);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPALIVE, 1L);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPIDLE, 60L);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPINTVL, 60L);
	curl_easy_setopt(curl, CURLOPT_HTTPAUTH, CURLAUTH_ANY);
	curl_easy_setopt(curl, CURLOPT_PRIVATE, (void *)payload);

}

int curl_download(dload_payload *payload) {
	CURL *curl;
	CURLcode res;
	char errbuf[CURL_ERROR_SIZE];
	errbuf[0] = 0;

	curl = curl_easy_init();
	payload->curl = curl;
	strcpy(payload->error_buffer, errbuf);

	curl_set_handle_opts(curl, payload);

	res = curl_easy_perform(curl);

	if(res != CURLE_OK) {
		size_t len = strlen(payload->error_buffer);
		fprintf(stderr, "\nlibcurl: (%d) ", res);
		if(len)
			fprintf(stderr, "%s%s", payload->error_buffer,
						((errbuf[len - 1] != '\n') ? "\n" : ""));
		else
			fprintf(stderr, "%s\n", curl_easy_strerror(res));
	}

	curl_easy_cleanup(curl);
	putchar('\n');

	return 0;

}
/*

static int curl_add_payload(CURLM *curlm, dload_payload *payload, const char *localpath)
{
	size_t len;
	CURL *curl = NULL;
	int ret = -1;

	curl = curl_easy_init();
	payload->curl = curl;

	curl_easy_setopt(curl, CURLOPT_WRITEDATA, payload->localf);
	curl_multi_add_handle(curlm, curl);

	return 0;

cleanup:
	curl_easy_cleanup(curl);
	return ret;
}

*/
