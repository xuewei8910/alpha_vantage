import aiohttp
from functools import wraps
import inspect
import re
# Pandas became an optional dependency, but we still want to track it
try:
    import pandas
    _PANDAS_FOUND = True
except ImportError:
    _PANDAS_FOUND = False
import csv
from ..alphavantage import AlphaVantage as AlphaVantageBase


class AlphaVantage(AlphaVantageBase):
    """
    Async version of the base class where the decorators and base function for
    the other classes of this python wrapper will inherit from.
    """

    def __init__(self, *args, proxy=None, **kwargs):
        super(AlphaVantage, self).__init__(*args, **kwargs)
        self.session = None
        self.proxy = proxy or ''

    @classmethod
    def _call_api_on_func(cls, func):
        """ Decorator for forming the api call with the arguments of the
        function, it works by taking the arguments given to the function
        and building the url to call the api on it

        Keyword Arguments:
            func:  The function to be decorated
        """

        # Argument Handling
        argspec = inspect.getfullargspec(func)
        try:
            # Asumme most of the cases have a mixed between args and named
            # args
            positional_count = len(argspec.args) - len(argspec.defaults)
            defaults = dict(
                zip(argspec.args[positional_count:], argspec.defaults))
        except TypeError:
            if argspec.args:
                # No defaults
                positional_count = len(argspec.args)
                defaults = {}
            elif argspec.defaults:
                # Only defaults
                positional_count = 0
                defaults = argspec.defaults
        # Actual decorating

        @wraps(func)
        async def _call_wrapper(self, *args, **kwargs):
            used_kwargs = kwargs.copy()
            # Get the used positional arguments given to the function
            used_kwargs.update(zip(argspec.args[positional_count:],
                                   args[positional_count:]))
            # Update the dictionary to include the default parameters from the
            # function
            used_kwargs.update({k: used_kwargs.get(k, d)
                                for k, d in defaults.items()})
            # Form the base url, the original function called must return
            # the function name defined in the alpha vantage api and the data
            # key for it and for its meta data.
            function_name, data_key, meta_data_key = func(
                self, *args, **kwargs)
            base_url = AlphaVantage._RAPIDAPI_URL if self.rapidapi else AlphaVantage._ALPHA_VANTAGE_API_URL
            url = "{}function={}".format(base_url, function_name)
            for idx, arg_name in enumerate(argspec.args[1:]):
                try:
                    arg_value = args[idx]
                except IndexError:
                    arg_value = used_kwargs[arg_name]
                if 'matype' in arg_name and arg_value:
                    # If the argument name has matype, we gotta map the string
                    # or the integer
                    arg_value = self.map_to_matype(arg_value)
                if arg_value:
                    # Discard argument in the url formation if it was set to
                    # None (in other words, this will call the api with its
                    # internal defined parameter)
                    if isinstance(arg_value, tuple) or isinstance(arg_value, list):
                        # If the argument is given as list, then we have to
                        # format it, you gotta format it nicely
                        arg_value = ','.join(arg_value)
                    url = '{}&{}={}'.format(url, arg_name, arg_value)
            # Allow the output format to be json or csv (supported by
            # alphavantage api). Pandas is simply json converted.
            if 'json' in self.output_format.lower() or 'csv' in self.output_format.lower():
                oformat = self.output_format.lower()
            elif 'pandas' in self.output_format.lower():
                oformat = 'json'
            else:
                raise ValueError("Output format: {} not recognized, only json,"
                                 "pandas and csv are supported".format(
                                     self.output_format.lower()))
            apikey_parameter = "" if self.rapidapi else "&apikey={}".format(
                self.key)
            if self._append_type:
                url = '{}{}&datatype={}'.format(url, apikey_parameter, oformat)
            else:
                url = '{}{}'.format(url, apikey_parameter)
            return await self._handle_api_call(url), data_key, meta_data_key
        return _call_wrapper

    @classmethod
    def _output_format_sector(cls, func, override=None):
        """ Decorator in charge of giving the output its right format, either
        json or pandas (replacing the % for usable floats, range 0-1.0)

        Keyword Arguments:
            func: The function to be decorated
            override: Override the internal format of the call, default None
        Returns:
            A decorator for the format sector api call
        """
        @wraps(func)
        async def _format_wrapper(self, *args, **kwargs):
            json_response, data_key, meta_data_key = await func(
                self, *args, **kwargs)
            if isinstance(data_key, list):
                # Replace the strings into percentage
                data = {key: {k: self.percentage_to_float(v)
                              for k, v in json_response[key].items()} for key in data_key}
            else:
                data = json_response[data_key]
            # TODO: Fix orientation in a better way
            meta_data = json_response[meta_data_key]
            # Allow to override the output parameter in the call
            if override is None:
                output_format = self.output_format.lower()
            elif 'json' or 'pandas' in override.lower():
                output_format = override.lower()
            # Choose output format
            if output_format == 'json':
                return data, meta_data
            elif output_format == 'pandas':
                data_pandas = pandas.DataFrame.from_dict(data,
                                                         orient='columns')
                # Rename columns to have a nicer name
                col_names = [re.sub(r'\d+.', '', name).strip(' ')
                             for name in list(data_pandas)]
                data_pandas.columns = col_names
                return data_pandas, meta_data
            else:
                raise ValueError('Format: {} is not supported'.format(
                    self.output_format))
        return _format_wrapper

    @classmethod
    def _output_format(cls, func, override=None):
        """ Decorator in charge of giving the output its right format, either
        json or pandas

        Keyword Arguments:
            func:  The function to be decorated
            override:  Override the internal format of the call, default None
        """
        @wraps(func)
        async def _format_wrapper(self, *args, **kwargs):
            call_response, data_key, meta_data_key = await func(
                self, *args, **kwargs)
            if 'json' in self.output_format.lower() or 'pandas' \
                    in self.output_format.lower():
                if data_key:
                    data = call_response[data_key]
                else:
                    data = call_response

                if meta_data_key is not None:
                    meta_data = call_response[meta_data_key]
                else:
                    meta_data = None
                # Allow to override the output parameter in the call
                if override is None:
                    output_format = self.output_format.lower()
                elif 'json' or 'pandas' in override.lower():
                    output_format = override.lower()
                # Choose output format
                if output_format == 'json':
                    return data, meta_data
                elif output_format == 'pandas':
                    if isinstance(data, list):
                        # If the call returns a list, then we will append them
                        # in the resulting data frame. If in the future
                        # alphavantage decides to do more with returning arrays
                        # this might become buggy. For now will do the trick.
                        data_array = []
                        for val in data:
                            data_array.append([v for _, v in val.items()])
                        data_pandas = pandas.DataFrame(data_array, columns=[
                            k for k, _ in data[0].items()])
                    else:
                        try:
                            data_pandas = pandas.DataFrame.from_dict(data,
                                                                     orient='index',
                                                                     dtype='float')
                        # This is for Global quotes or any other new Alpha Vantage
                        # data that is added.
                        # It will have to be updated so that we can get exactly
                        # The dataframes we want moving forward
                        except ValueError:
                            data = {data_key: data}
                            data_pandas = pandas.DataFrame.from_dict(data,
                                                                     orient='index',
                                                                     dtype='object')
                            return data_pandas, meta_data

                    if 'integer' in self.indexing_type:
                        # Set Date as an actual column so a new numerical index
                        # will be created, but only when specified by the user.
                        data_pandas.reset_index(level=0, inplace=True)
                        data_pandas.index.name = 'index'
                    else:
                        data_pandas.index.name = 'date'
                        # convert to pandas._libs.tslibs.timestamps.Timestamp
                        data_pandas.index = pandas.to_datetime(
                            data_pandas.index)
                    return data_pandas, meta_data
            elif 'csv' in self.output_format.lower():
                return call_response, None
            else:
                raise ValueError('Format: {} is not supported'.format(
                    self.output_format))
        return _format_wrapper

    def set_proxy(self, proxy=None):
        """
        Set a new proxy configuration

        Keyword Arguments:
            proxy: String URL of the proxy.
        """
        self.proxy = proxy or ''

    async def _handle_api_call(self, url):
        """
        Handle the return call from the  api and return a data and meta_data
        object. It raises a ValueError on problems

        Keyword Arguments:
            url:  The url of the service
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        response = await self.session.get(url, proxy=self.proxy, headers=self.headers)
        if 'json' in self.output_format.lower() or 'pandas' in \
                self.output_format.lower():
            json_response = await response.json()
            if not json_response:
                raise ValueError(
                    'Error getting data from the api, no return was given.')
            elif "Error Message" in json_response:
                raise ValueError(json_response["Error Message"])
            elif "Information" in json_response and self.treat_info_as_error:
                raise ValueError(json_response["Information"])
            elif "Note" in json_response and self.treat_info_as_error:
                raise ValueError(json_response["Note"])
            return json_response
        else:
            csv_response = csv.reader(response.text.splitlines())
            if not csv_response:
                raise ValueError(
                    'Error getting data from the api, no return was given.')
            return csv_response

    async def close(self):
        """
        Close the underlying aiohttp session
        """
        if self.session and not self.session.closed:
            await self.session.close()
