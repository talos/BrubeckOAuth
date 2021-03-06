#!/usr/bin/env python
import sys
import urllib2
import functools
import logging
import os
import time
import md5
import base64
import hmac
import hashlib
import httplib
import random
import json
import datetime
import imp
import uuid

import requests
from urllib import unquote, quote
from brubeck.auth import authenticated
from brubeck.queryset import DictQueryset
from brubeck.request_handling import Brubeck, WebMessageHandler, JSONMessageHandler, cookie_encode, cookie_decode
from brubeck.templating import load_jinja2_env, Jinja2Rendering
from dictshield import fields
from dictshield.document import Document
from dictshield.fields import ShieldException

from models import OAuthRequest
from base import lazyprop, OAuthBase

## This is the built in data store for the OAuthRequest
## If you want to run wore than one instance of this application
## you will need to overide oauth_request_queryset
## with you own implementation.
oauth_request_queryset = DictQueryset()

##################################################
# Test handler 
##################################################
class OAuthRedirectorTestHandler(object):
    """Our development oAuth handler.
    parses a predifined callback from oAuth[PROVIDERS][{providername}]
    """
    def get(self, settings):
        # we are in development, fake it
        logging.debug( "facebook faking it" );
        user = find_user_by_username(self.username)
        oauth_data = settings['TEST_OAUTH_DATA']
        # we should store this data now
        if user == None:
            user = User(
                username=self.username,
                nickname=oauth_data['username'],
                current_oauth_provider='facebook',
                oauth_data=json.dumps(oauth_data)
            )
        else:
            user.nickname = oauth_data['username']
            user.current_oauth_provider = 'facebook'
            user.oauth_data = json.dumps(oauth_data)
        
        # adding an existing key just replaces it
        add_user(user)
        return self.redirect("/oauth/facebook/loggedin")


###############################################
# The handler mixin we actualy use for routing
###############################################

class OAuthMixin(object):
    """oauth routing handler mixin. All requests come through here.
    You should use this as a mixin for your WebMessageHandler and 
    implement the methods onAuthenticationSuccess and 
    onAuthenticationFailure.
    """

    @lazyprop
    def settings(self):
        """used to define the supported providers configurations"""
        return self.application.get_settings('oauth')

    @lazyprop
    def oauth_token(self):
        """ oauth_token argument.
        used by oauth1a to track request and response to same user.
        """
        return self.get_argument('oauth_token', None)

    @lazyprop
    def state(self):
        """ state argument.
        used by oauth2 to track request and response to same user.
        """
        return self.get_argument('state', None)

    @lazyprop
    def oauth_verifier(self):
        """ argument returned by auth calls
        """
        return self.get_argument('oauth_verifier', None)

    @lazyprop
    def oauth_base(self):
        """ Our oAuth base object (not oauth version specific).
        """
        return OAuthBase()

    @lazyprop
    def oauth_request_model(self):
        """ Our model containing state from the oauth request process.
        """
        model = None
        if self.oauth_token != None:
            data = self.oauth_request_queryset.read_one(self.oauth_token)[1]
            model = OAuthRequest(**data)
        if model == None and self.state != None:
            data = self.oauth_request_queryset.read_one(self.state)[1]
            model = OAuthRequest(**data)
        return model

    @lazyprop
    def oauth_token(self):
        """ oauth_token argument sent by the provider
        """
        return self.get_argument('oauth_token', None)

    @lazyprop
    def oauth_request_queryset(self):
        """ the queryset to manage our oauuth_request persistance
        (defaults to in memory DictQueryset).
        """
        return oauth_request_queryset

    def get(self, provider, action):
        """Loads the provider config and 
        routes our request to the proper base methods.
        """
        try:
            logging.debug("oauth GET %s %s" % (provider, action))
            # logging.debug(self.settings)
            # see if we are in test mode
            if ("OAUTH_TEST" in self.settings and
                self.settings["OAUTH_TEST"] == True):
                # skip all the formalities and use our canned response
                return OAuthRedirectorTestHandler.get(self, self.settings)
            if not provider in self.settings['PROVIDERS']:
                raise Exception("Unsupported provider: %s" % provider)
            provider_settings = self.settings['PROVIDERS'][provider]            
            logging.debug("provider_settings -> \n%s" % provider_settings)
            oauth_object = self.oauth_base.get_oauth_object(provider_settings)
            # respond to the proper action
            if action == 'login':
                return self.redirect(oauth_object.redirector(provider_settings,
                    self.oauth_request_queryset,
                    self.session_id))
            elif action == 'callback':
                logging.debug(self.message.arguments)
                self._oauth_request_model = oauth_object.callback(
                    provider_settings,
                    self.oauth_request_model, 
                    self.oauth_token, 
                    self.oauth_verifier,
                    self.session_id,
                    self.message.arguments
                )
                return self.onAuthenticationSuccess(self.oauth_request_model)
            else:
                raise Exception("Unsupported action: " + action)
        except Exception as e:
            raise
            self.set_status(200)
            self.add_to_payload('messages', e)
            return self.render()
        # if we got here, we have problems
        self.set_status(403)
        self.add_to_payload('messages', "Unknown oauth error")
        return self.render();

    def onAuthenticationSuccess(self, oauth_request_model):
        """it is the applications responsibilty to extend this class and
        implement this method to hook into the rest of the applications 
        authentication and user handling.
        The oauth_request_model is by default 
        not persisted beyond this function.
        """
        raise NotImplementedError

    def onAuthenticationFailure(self, oauth_request_model):
        """Failure is harsh, deal with it more gracefully if you want to.
        """
        raise Exception("Authentication failed!")
