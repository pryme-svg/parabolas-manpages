#include <curl/curl.h>

static void curl_set_handle_opts(CURL *curl, struct dload_payload *payload)
{
	const char *useragent = getenv("HTTP_USER_AGENT");
	struct stat st;

	curl_easy_reset(curl);
	curl_easy_setopt(curl, CURLOPT_USERAGENT, "Man page crawler (info@parabolas.xyz; https://man.parabolas.xyz/)");
	curl_easy_setopt(curl, CURLOPT_URL, payload->fileurl);
	curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, payload->error_buffer);
	curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
	curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 10L);
	curl_easy_setopt(curl, CURLOPT_FILETIME, 1L);
	curl_easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
	curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
	curl_easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, dload_progress_cb);
	curl_easy_setopt(curl, CURLOPT_XFERINFODATA, (void *)payload);
	if(!handle->disable_dl_timeout) {
		curl_easy_setopt(curl, CURLOPT_LOW_SPEED_LIMIT, 1L);
		curl_easy_setopt(curl, CURLOPT_LOW_SPEED_TIME, 10L);
	}
	curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, dload_parseheader_cb);
	curl_easy_setopt(curl, CURLOPT_HEADERDATA, (void *)payload);
	curl_easy_setopt(curl, CURLOPT_NETRC, CURL_NETRC_OPTIONAL);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPALIVE, 1L);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPIDLE, 60L);
	curl_easy_setopt(curl, CURLOPT_TCP_KEEPINTVL, 60L);
	curl_easy_setopt(curl, CURLOPT_HTTPAUTH, CURLAUTH_ANY);
	curl_easy_setopt(curl, CURLOPT_PRIVATE, (void *)payload);

	_alpm_log(handle, ALPM_LOG_DEBUG, "%s: url is %s\n",
		payload->remote_name, payload->fileurl);

	if(payload->max_size) {
		_alpm_log(handle, ALPM_LOG_DEBUG, "%s: maxsize %jd\n",
				payload->remote_name, (intmax_t)payload->max_size);
		curl_easy_setopt(curl, CURLOPT_MAXFILESIZE_LARGE,
				(curl_off_t)payload->max_size);
	}

	if(useragent != NULL) {
	}

	if(!payload->force && payload->destfile_name &&
			stat(payload->destfile_name, &st) == 0) {
		/* start from scratch, but only download if our local is out of date. */
		curl_easy_setopt(curl, CURLOPT_TIMECONDITION, CURL_TIMECOND_IFMODSINCE);
		curl_easy_setopt(curl, CURLOPT_TIMEVALUE, (long)st.st_mtime);
		_alpm_log(handle, ALPM_LOG_DEBUG,
				"%s: using time condition %ld\n",
				payload->remote_name, (long)st.st_mtime);
	} else if(stat(payload->tempfile_name, &st) == 0 && payload->allow_resume) {
		/* a previous partial download exists, resume from end of file. */
		payload->tempfile_openmode = "ab";
		curl_easy_setopt(curl, CURLOPT_RESUME_FROM_LARGE, (curl_off_t)st.st_size);
		_alpm_log(handle, ALPM_LOG_DEBUG,
				"%s: tempfile found, attempting continuation from %jd bytes\n",
				payload->remote_name, (intmax_t)st.st_size);
		payload->initial_size = st.st_size;
	}
}

int curl_download(struct dload_payload *payload) {
	CURL *curl;

	curl = curl_easy_init();
	payload->curl = curl;

	curl_set_handle_opts(curl, payload);

}

static int curl_add_payload(alpm_handle_t *handle, CURLM *curlm,
		struct dload_payload *payload, const char *localpath)
{
	size_t len;
	CURL *curl = NULL;
	char hostname[HOSTNAME_SIZE];
	int ret = -1;

	curl = curl_easy_init();
	payload->curl = curl;

	if(payload->fileurl) {
		ASSERT(!payload->servers, GOTO_ERR(handle, ALPM_ERR_WRONG_ARGS, cleanup));
		ASSERT(!payload->filepath, GOTO_ERR(handle, ALPM_ERR_WRONG_ARGS, cleanup));
	} else {
		const char *server;
		while(payload->servers && should_skip_server(handle, payload->servers->data)) {
			payload->servers = payload->servers->next;
		}

		ASSERT(payload->servers, GOTO_ERR(handle, ALPM_ERR_SERVER_NONE, cleanup));
		ASSERT(payload->filepath, GOTO_ERR(handle, ALPM_ERR_WRONG_ARGS, cleanup));

		server = payload->servers->data;
		payload->servers = payload->servers->next;

		len = strlen(server) + strlen(payload->filepath) + 2;
		MALLOC(payload->fileurl, len, GOTO_ERR(handle, ALPM_ERR_MEMORY, cleanup));
		snprintf(payload->fileurl, len, "%s/%s", server, payload->filepath);
	}

	payload->tempfile_openmode = "wb";
	if(!payload->remote_name) {
		STRDUP(payload->remote_name, get_filename(payload->fileurl),
			GOTO_ERR(handle, ALPM_ERR_MEMORY, cleanup));
	}
	if(curl_gethost(payload->fileurl, hostname, sizeof(hostname)) != 0) {
		_alpm_log(handle, ALPM_LOG_ERROR, _("url '%s' is invalid\n"), payload->fileurl);
		GOTO_ERR(handle, ALPM_ERR_SERVER_BAD_URL, cleanup);
	}

	if(!payload->random_partfile && payload->remote_name && strlen(payload->remote_name) > 0) {
		if(!payload->destfile_name) {
			payload->destfile_name = get_fullpath(localpath, payload->remote_name, "");
		}
		payload->tempfile_name = get_fullpath(localpath, payload->remote_name, ".part");
		if(!payload->destfile_name || !payload->tempfile_name) {
			goto cleanup;
		}
	} else {
		/* We want a random filename or the URL does not contain a filename, so download to a
		 * temporary location. We can not support resuming this kind of download; any partial
		 * transfers will be destroyed */
		payload->unlink_on_fail = 1;

		payload->localf = create_tempfile(payload, localpath);
		if(payload->localf == NULL) {
			goto cleanup;
		}
	}

	curl_set_handle_opts(curl, payload);

	if(payload->max_size == payload->initial_size && payload->max_size != 0) {
		/* .part file is complete */
		ret = 0;
		goto cleanup;
	}

	if(payload->localf == NULL) {
		payload->localf = fopen(payload->tempfile_name, payload->tempfile_openmode);
		if(payload->localf == NULL) {
			_alpm_log(handle, ALPM_LOG_ERROR,
					_("could not open file %s: %s\n"),
					payload->tempfile_name, strerror(errno));
			GOTO_ERR(handle, ALPM_ERR_RETRIEVE, cleanup);
		}
	}

	_alpm_log(handle, ALPM_LOG_DEBUG,
			"%s: opened tempfile for download: %s (%s)\n",
			payload->remote_name,
			payload->tempfile_name,
			payload->tempfile_openmode);

	curl_easy_setopt(curl, CURLOPT_WRITEDATA, payload->localf);
	curl_multi_add_handle(curlm, curl);

	if(handle->dlcb) {
		alpm_download_event_init_t cb_data = {.optional = payload->errors_ok};
		handle->dlcb(handle->dlcb_ctx, payload->remote_name, ALPM_DOWNLOAD_INIT, &cb_data);
	}

	return 0;

cleanup:
	curl_easy_cleanup(curl);
	return ret;
}
