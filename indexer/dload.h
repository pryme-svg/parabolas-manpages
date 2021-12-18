#ifndef DLOAD_H
#define DLOAD_H

#include <curl/curl.h>

typedef struct dload_payload {
	char *content_disp_name;
	char *fileurl;

	int write_string; /* write content to dest_string */
	char *dest_string;

	long respcode;
	int unlink_on_fail;
	int download_signature; /* specifies if an accompanion *.sig file need to be downloaded*/
	int signature_optional; /* *.sig file is optional */
	CURL *curl;
	char error_buffer[CURL_ERROR_SIZE];
	FILE *localf; /* destination download file */
	int signature; /* specifies if this payload is for a signature file */
} dload_payload;

int curl_download(dload_payload *payload);

#endif
