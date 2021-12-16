#ifndef DLOAD_H
#define DLOAD_H

typedef struct dload_payload {
	const char *tempfile_openmode;
	char *remote_name;
	char *tempfile_name;
	char *destfile_name;
	char *content_disp_name;
	/* client has to provide either
	 *  1) fileurl - full URL to the file
	 *  2) pair of (servers, filepath), in this case ALPM iterates over the
	 *     server list and tries to download "$server/$filepath"
	 */
	char *fileurl;
	char *filepath; /* download URL path */
	long respcode;
	off_t initial_size;
	off_t max_size;
	off_t prevprogress;
	int force;
	int allow_resume;
	int random_partfile;
	int errors_ok;
	int unlink_on_fail;
	int trust_remote_name;
	int download_signature; /* specifies if an accompanion *.sig file need to be downloaded*/
	int signature_optional; /* *.sig file is optional */
	CURL *curl;
	char error_buffer[CURL_ERROR_SIZE];
	FILE *localf; /* temp download file */
	int signature; /* specifies if this payload is for a signature file */
} dload_payload;

int _download(dload_payload *payload);

#endif
