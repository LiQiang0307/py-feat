from __future__ import division

"""Class definitions."""

import os, warnings
from os.path import join
import numpy as np
import pandas as pd
from pandas import DataFrame, Series, Index
from copy import deepcopy
from functools import reduce
from nltools.data import Adjacency, design_matrix
from nltools.stats import downsample, upsample, transform_pairwise, regress
from nltools.utils import set_decomposition_algorithm
from sklearn.metrics.pairwise import pairwise_distances, cosine_similarity
from sklearn.utils import check_random_state
from sklearn.linear_model import LinearRegression

from feat.utils import (
    read_feat,
    read_affectiva,
    read_facet,
    read_openface,
    wavelet,
    calc_hist_auc,
    load_h5,
    get_resource_path,
)
from feat.plotting import plot_face, draw_lineface, draw_muscles
from nilearn.signal import clean
from scipy.signal import convolve
from scipy.stats import ttest_1samp, ttest_ind


class FexSeries(Series):
    """
    This is a sub-class of pandas series. While not having additional methods
    of it's own required to retain normal slicing functionality for the
    Fex class, i.e. how slicing is typically handled in pandas.
    All methods should be called on Fex below.
    """

    _metadata = [
        "au_columns",
        "emotion_columns",
        "facebox_columns",
        "landmark_columns",
        "facepose_columns",
        "gaze_columns",
        "time_columns",
        "design_columns",
        "fex_columns",
        "filename",
        "sampling_freq",
        "features",
        "sessions",
        "detector",
    ]

    def __init__(self, *args, **kwargs):
        ### Columns ###
        self.au_columns = kwargs.pop("au_columns", None)
        self.emotion_columns = kwargs.pop("emotion_columns", None)
        self.facebox_columns = kwargs.pop("facebox_columns", None)
        self.landmark_columns = kwargs.pop("landmark_columns", None)
        self.facepose_columns = kwargs.pop("facepose_columns", None)
        self.gaze_columns = kwargs.pop("gaze_columns", None)
        self.time_columns = kwargs.pop("time_columns", None)
        self.design_columns = kwargs.pop("design_columns", None)

        ### Meta data ###
        self.filename = kwargs.pop("filename", None)
        self.sampling_freq = kwargs.pop("sampling_freq", None)
        self.detector = kwargs.pop("detector", None)
        self.features = kwargs.pop("features", None)
        self.sessions = kwargs.pop("sessions", None)
        super().__init__(*args, **kwargs)

    @property
    def _constructor(self):
        return FexSeries

    @property
    def _constructor_expanddim(self):
        return Fex

    def __finalize__(self, other, method=None, **kwargs):
        """Propagate metadata from other to self
        
        """
        # NOTE: backported from pandas master (upcoming v0.13)
        for name in self._metadata:
            object.__setattr__(self, name, getattr(other, name, None))
        return self

    def aus(self):
        """Returns the Action Units data

        Returns:
            DataFrame: Action Units data
        """
        return self[self.au_columns]

    def emotions(self):
        """Returns the emotion data

        Returns:
            DataFrame: emotion data
        """
        return self[self.emotion_columns]

    def landmark(self):
        """Returns the landmark data

        Returns:
            DataFrame: landmark data
        """
        return self[self.landmark_columns]

    def input(self):
        """Returns input column as string

        Returns:
            string: path to input image
        """
        return self["input"]

    def landmark_x(self):
        """Returns the x landmarks.

        Returns:
            DataFrame: x landmarks.
        """
        ######## TODO: NATSORT columns before returning #######
        x_cols = [col for col in self.landmark_columns if "x" in col]
        return self[x_cols]

    def landmark_y(self):
        """Returns the y landmarks.

        Returns:
            DataFrame: y landmarks.
        """
        y_cols = [col for col in self.landmark_columns if "y" in col]
        return self[y_cols]

    def facebox(self):
        """Returns the facebox data

        Returns:
            DataFrame: facebox data
        """
        return self[self.facebox_columns]

    def time(self):
        """Returns the time data

        Returns:
            DataFrame: time data
        """
        return self[self.time_columns]

    def design(self):
        """Returns the design data

        Returns:
            DataFrame: time data
        """
        return self[self.design_columns]

    def info(self):
        """Print class meta data."""
        attr_list = []
        for name in self._metadata:
            attr_list.append(name + ": " + str(getattr(self, name, None)) + "\n")
        print(f"{self.__class__}\n" + "".join(attr_list))


class Fex(DataFrame):
    """Fex is a class to represent facial expression (Fex) data
    
    Fex class is  an enhanced pandas dataframe, with extra attributes and methods to help with facial expression data analysis.

    Args:
        filename: (str, optional) path to file
        detector: (str, optional) name of software used to extract Fex. (Feat, FACET, OpenFace, or Affectiva)
        sampling_freq (float, optional): sampling rate of each row in Hz; defaults to None
        features (pd.Dataframe, optional): features that correspond to each Fex row
        sessions: Unique values indicating rows associated with a specific session (e.g., trial, subject, etc).Must be a 1D array of n_samples elements; defaults to None
    """

    # __metaclass__  = abc.ABCMeta

    # Need to specify attributes for pandas.
    _metadata = [
        "au_columns",
        "emotion_columns",
        "facebox_columns",
        "landmark_columns",
        "facepose_columns",
        "gaze_columns",
        "time_columns",
        "design_columns",
        "fex_columns",
        "filename",
        "sampling_freq",
        "features",
        "sessions",
        "detector",
    ]

    def __finalize__(self, other, method=None, **kwargs):
        """Propagate metadata from other to self """
        self = super().__finalize__(other, method=method, **kwargs)
        # merge operation: using metadata of the left object
        if method == "merge":
            for name in self._metadata:
                print("self", name, self.au_columns, other.left.au_columns)
                object.__setattr__(self, name, getattr(other.left, name, None))
        # concat operation: using metadata of the first object
        elif method == "concat":
            for name in self._metadata:
                object.__setattr__(self, name, getattr(other.objs[0], name, None))
        return self

    def __init__(self, *args, **kwargs):
        ### Columns ###
        self.au_columns = kwargs.pop("au_columns", None)
        self.emotion_columns = kwargs.pop("emotion_columns", None)
        self.facebox_columns = kwargs.pop("facebox_columns", None)
        self.landmark_columns = kwargs.pop("landmark_columns", None)
        self.facepose_columns = kwargs.pop("facepose_columns", None)
        self.gaze_columns = kwargs.pop("gaze_columns", None)
        self.time_columns = kwargs.pop("time_columns", None)
        self.design_columns = kwargs.pop("design_columns", None)

        ### Meta data ###
        self.filename = kwargs.pop("filename", None)
        self.sampling_freq = kwargs.pop("sampling_freq", None)
        self.detector = kwargs.pop("detector", None)
        self.features = kwargs.pop("features", None)
        self.sessions = kwargs.pop("sessions", None)

        super().__init__(*args, **kwargs)
        if self.sessions is not None:
            if not len(self.sessions) == len(self):
                raise ValueError("Make sure sessions is same length as data.")
            self.sessions = np.array(self.sessions)
        # if (self.fex_columns is None) and (not self._metadata):
        #     try:
        #         self.fex_columns = self._metadata
        #     except:
        #         print('Failed to import _metadata to fex_columns')

        # Set _metadata attributes on series: Kludgy solution
        for k in self:
            self[k].sampling_freq = self.sampling_freq
            self[k].sessions = self.sessions

    @property
    def _constructor(self):
        return Fex

    @property
    def _constructor_sliced(self):
        return FexSeries

    def _ixs(self, i, axis=0):
        """Override indexing to ensure Fex._metadata is propogated correctly
            when integer indexing

        i : int, slice, or sequence of integers
        axis : int
        """
        result = super()._ixs(i, axis=axis)

        # Override columns
        if axis == 0:
            if isinstance(i, slice):
                return self[i]
            else:
                label = self.index[i]
                if isinstance(label, Index):
                    # a location index by definition
                    result = self.take(i, axis=axis)
                    copy = True
                else:
                    new_values = self._data.fast_xs(i)

                    # if we are a copy, mark as such
                    copy = (
                        isinstance(new_values, np.ndarray) and new_values.base is None
                    )
                    result = self._constructor_sliced(
                        new_values,
                        index=self.columns,
                        name=self.index[i],
                        dtype=new_values.dtype,
                        au_columns=self.au_columns,
                        emotion_columns=self.emotion_columns,
                        facebox_columns=self.facebox_columns,
                        landmark_columns=self.landmark_columns,
                        facepose_columns=self.facepose_columns,
                        gaze_columns=self.gaze_columns,
                        time_columns=self.time_columns,
                        design_columns=self.design_columns,
                        filename=self.filename,
                        sampling_freq=self.sampling_freq,
                        detector=self.detector,
                        features=self.features,
                        sessions=self.sessions,
                    )
                result._set_is_copy(self, copy=copy)
                return result

        else:
            """
            Notes
            -----
            If slice passed, the resulting data will be a view
            """

            label = self.columns[i]
            if isinstance(i, slice):
                # need to return view
                lab_slice = slice(label[0], label[-1])
                return self.loc[:, lab_slice]
            else:
                if isinstance(label, Index):
                    return self._take(i, axis=1, convert=True)

                index_len = len(self.index)

                # if the values returned are not the same length
                # as the index (iow a not found value), iget returns
                # a 0-len ndarray. This is effectively catching
                # a numpy error (as numpy should really raise)
                values = self._data.iget(i)

                if index_len and not len(values):
                    values = np.array([np.nan] * index_len, dtype=object)
                result = self._constructor_sliced(
                    values,
                    index=self.index,
                    name=label,
                    fastpath=True,
                    au_columns=self.au_columns,
                    emotion_columns=self.emotion_columns,
                    facebox_columns=self.facebox_columns,
                    landmark_columns=self.landmark_columns,
                    facepose_columns=self.facepose_columns,
                    gaze_columns=self.gaze_columns,
                    time_columns=self.time_columns,
                    design_columns=self.design_columns,
                    filename=self.filename,
                    sampling_freq=self.sampling_freq,
                    detector=self.detector,
                    features=self.features,
                    sessions=self.sessions,
                )

                # this is a cached value, mark it so
                result._set_as_cached(label, self)
                return result

    def aus(self):
        """Returns the Action Units data

        Returns Action Unit data using the columns set in fex.au_columns.

        Returns:
            DataFrame: Action Units data
        """
        return self[self.au_columns]

    def emotions(self):
        """Returns the emotion data

        Returns emotions data using the columns set in fex.emotion_columns.

        Returns:
            DataFrame: emotion data
        """
        return self[self.emotion_columns]

    def landmark(self):
        """Returns the landmark data

        Returns landmark data using the columns set in fex.landmark_columns.

        Returns:
            DataFrame: landmark data
        """
        return self[self.landmark_columns]

    def input(self):
        """Returns input column as string

        Returns input data in the "input" column.

        Returns:
            string: path to input image
        """
        return self["input"]

    def landmark_x(self):
        """Returns the x landmarks.

        Returns the x-coordinates for facial landmarks looking for "x" in fex.landmark_columns.

        Returns:
            DataFrame: x landmarks.
        """
        ######## TODO: NATSORT columns before returning #######
        x_cols = [col for col in self.landmark_columns if "x" in col]
        return self[x_cols]

    def landmark_y(self):
        """Returns the y landmarks.

        Returns the y-coordinates for facial landmarks looking for "y" in fex.landmark_columns.

        Returns:
            DataFrame: y landmarks.
        """
        y_cols = [col for col in self.landmark_columns if "y" in col]
        return self[y_cols]

    def facebox(self):
        """Returns the facebox data

        Returns the facebox data using fex.facebox_columns.

        Returns:
            DataFrame: facebox data
        """
            
        return self[self.facebox_columns]

    def time(self):
        """Returns the time data

        Returns the time information using fex.time_columns.

        Returns:
            DataFrame: time data
        """
        return self[self.time_columns]

    def design(self):
        """Returns the design data

        Returns the study design information using columns in fex.design_columns.

        Returns:
            DataFrame: time data
        """
        return self[self.design_columns]

    def read_file(self, *args, **kwargs):
        """Loads file into FEX class

        This function checks the detector set in fex.detector and calls the appropriate read function that helps utilize functionalities of Feat. 

        Available detectors include:
            FACET
            OpenFace
            Affectiva
            Feat

        Returns:
            DataFrame: Fex class
        """
        if self.detector == "FACET":
            return self.read_facet(self.filename)
        elif self.detector == "OpenFace":
            return self.read_openface(self.filename)
        elif self.detector == "Affectiva":
            return self.read_affectiva(self.filename)
        elif self.detector == "Feat":
            return self.read_feat(self.filename)
        else:
            print("Must specifiy which detector [Feat, FACET, OpenFace, or Affectiva]")

    def info(self):
        """Print all meta data of fex
        
        Loops through metadata set in self._metadata and prints out the information.
        """
        attr_list = []
        for name in self._metadata:
            attr_list.append(name + ": " + str(getattr(self, name, None)) + "\n")
        print(f"{self.__class__}\n" + "".join(attr_list))

    ###   Class Methods   ###
    def read_feat(self, filename=None, *args, **kwargs):
        """Reads facial expression detection results from Feat Detector

        Args:
            filename (string, optional): Path to file. Defaults to None.

        Returns:
            Fex
        """ 
        # Check if filename exists in metadata.
        if not filename:
            try:
                filename = self.filename
            except:
                print("filename must be specified.")
        result = read_feat(filename, *args, **kwargs)
        return result

    def read_facet(self, filename=None, *args, **kwargs):
        """Reads facial expression detection results from FACET 

        Args:
            filename (string, optional): Path to file. Defaults to None.

        Returns:
            Fex
        """ 
        # Check if filename exists in metadata.
        if not filename:
            try:
                filename = self.filename
            except:
                print("filename must be specified.")
        result = read_facet(filename, *args, **kwargs)
        for name in self._metadata:
            attr_value = getattr(self, name, None)
            if attr_value and getattr(result, name, None) == None:
                setattr(result, name, attr_value)
        return result

    def read_openface(self, filename=None, *args, **kwargs):
        """Reads facial expression detection results from OpenFace 

        Args:
            filename (string, optional): Path to file. Defaults to None.

        Returns:
            Fex
        """
        if not filename:
            try:
                filename = self.filename
            except:
                print("filename must be specified.")
        result = read_openface(filename, *args, **kwargs)
        for name in self._metadata:
            attr_value = getattr(self, name, None)
            if attr_value and getattr(result, name, None) == None:
                setattr(result, name, attr_value)
        return result

    def read_affectiva(self, filename=None, *args, **kwargs):
        """Reads facial expression detection results from Affectiva 

        Args:
            filename (string, optional): Path to file. Defaults to None.

        Returns:
            Fex
        """
        if not filename:
            try:
                filename = self.filename
            except:
                print("filename must be specified.")
        result = read_affectiva(filename, *args, **kwargs)
        for name in self._metadata:
            attr_value = getattr(self, name, None)
            if attr_value and getattr(result, name, None) == None:
                setattr(result, name, attr_value)
        return result

    def itersessions(self):
        """Iterate over Fex sessions as (session, series) pairs.

        Returns:
            it: a generator that iterates over the sessions of the fex instance

        """
        for x in np.unique(self.sessions):
            yield x, self.loc[self.sessions == x, :]

    def append(self, data, session_id=None, axis=0):
        """Append a new Fex object to an existing object

        Args:
            data: (Fex) Fex instance to append
            session_id: session label
            axis: ([0,1]) Axis to append. Rows=0, Cols=1
        Returns:
            Fex instance
        """
        if not isinstance(data, self.__class__):
            raise ValueError("Make sure data is a Fex instance.")

        if self.empty:
            out = data.copy()
            if session_id is not None:
                out.sessions = np.repeat(session_id, len(data))
        else:
            if self.sampling_freq != data.sampling_freq:
                raise ValueError(
                    "Make sure Fex objects have the same " "sampling frequency"
                )
            if axis == 0:
                out = self.__class__(
                    pd.concat([self, data], axis=axis, ignore_index=True),
                    sampling_freq=self.sampling_freq,
                ).__finalize__(self)
                if session_id is not None:
                    out.sessions = np.hstack(
                        [self.sessions, np.repeat(session_id, len(data))]
                    )
                if self.features is not None:
                    if data.features is not None:
                        if self.features.shape[1] == data.features.shape[1]:
                            out.features = self.features.append(
                                data.features, ignore_index=True
                            )
                        else:
                            raise ValueError(
                                "Different number of features in new dataset."
                            )
                    else:
                        out.features = self.features
                elif data.features is not None:
                    out = data.features
            elif axis == 1:
                out = self.__class__(
                    pd.concat([self, data], axis=axis), sampling_freq=self.sampling_freq
                ).__finalize__(self)
                if self.sessions is not None:
                    if data.sessions is not None:
                        if np.array_equal(self.sessions, data.sessions):
                            out.sessions = self.sessions
                        else:
                            raise ValueError("Both sessions must be identical.")
                    else:
                        out.sessions = self.sessions
                elif data.sessions is not None:
                    out.sessions = data.sessions
                if self.features is not None:
                    out.features = self.features
                    if data.features is not None:
                        out.features.append(data.features, axis=1, ignore_index=True)
                elif data.features is not None:
                    out.features = data.features
            else:
                raise ValueError("Axis must be 1 or 0.")
        return out

    def regress(self, X, y, fit_intercept=True, *args, **kwargs):
        """Regress using nltools.stats.regress.

        fMRI-like regression to predict Fex activity (y) from set of regressors (X).

        Args:
            X (list or str): Independent variable to predict.
            y (list or str): Dependent variable to be predicted.
            fit_intercept (bool): Whether to add intercept before fitting. Defaults to True.

        Returns:
            betas, t-stats, p-values, df, residuals
        """
        if type(X) == list:
            mX = self[X]
        else:
            mX = X

        if fit_intercept:
            mX["intercept"] = 1

        if type(y) == str:
            my = self[y]
        else:
            my = y
        b, t, p, df, res = regress(mX, my, *args, **kwargs)
        b_df = pd.DataFrame(b, index=mX.columns, columns=my.columns)
        t_df = pd.DataFrame(t, index=mX.columns, columns=my.columns)
        p_df = pd.DataFrame(p, index=mX.columns, columns=my.columns)
        df_df = pd.DataFrame([df], index=[0], columns=my.columns)
        res_df = pd.DataFrame(res, columns=my.columns)
        return b_df, t_df, p_df, df_df, res_df

    def ttest_1samp(self, popmean=0, threshold_dict=None):
        """Conducts 1 sample ttest.

        Uses scipy.stats.ttest_1samp to conduct 1 sample ttest

        Args:
            popmean (int, optional): Population mean to test against. Defaults to 0.
            threshold_dict ([type], optional): Dictonary for thresholding. Defaults to None. [NOT IMPLEMENTED]

        Returns:
            t, p: t-statistics and p-values
        """
        return ttest_1samp(self, popmean)

    def ttest_ind(self, col, sessions, threshold_dict=None):
        """Conducts 2 sample ttest.

        Uses scipy.stats.ttest_ind to conduct 2 sample ttest on column col between sessions.

        Args:
            col (str): Column names to compare in a t-test between sessions
            session_names (tuple): tuple of session names stored in Fex.sessions.
            threshold_dict ([type], optional): Dictonary for thresholding. Defaults to None. [NOT IMPLEMENTED]

        Returns:
            t, p: t-statistics and p-values
        """
        sess1, sess2 = sessions
        a = self[self.sessions == sess1][col]
        b = self[self.sessions == sess2][col]
        return ttest_ind(a, b)

    def predict(self, X, y, model=LinearRegression, *args, **kwargs):
        """Predicts y from X using a sklearn model.

        Predict a variable of interest y using your model of choice from X, which can be a list of columns of the Fex instance or a dataframe.

        Args:
            X (list or DataFrame): List of column names or dataframe to be used as features for prediction
            y (string or array): y values to be predicted
            model (class, optional): Any sklearn model. Defaults to LinearRegression.
            *args, **kwargs: Model arguments

        Returns:
            model: Fit model instance.
        """
        if type(X) == list:
            mX = self[X]
        else:
            mX = X

        if type(y) == str:
            my = self[y]
        else:
            my = y
        clf = model(*args, **kwargs)
        clf.fit(mX, my)
        return clf

    def downsample(self, target, **kwargs):
        """Downsample Fex columns. Relies on nltools.stats.downsample,
           but ensures that returned object is a Fex object.

        Args:
            target(float): downsampling target, typically in samples not
                            seconds
            kwargs: additional inputs to nltools.stats.downsample

        """
        df_ds = downsample(
            self, sampling_freq=self.sampling_freq, target=target, **kwargs
        ).__finalize__(self)
        df_ds.sampling_freq = target

        if self.features is not None:
            ds_features = downsample(
                self.features, sampling_freq=self.sampling_freq, target=target, **kwargs
            )
        else:
            ds_features = self.features
        df_ds.features = ds_features
        return df_ds
        # return self.__class__(df_ds, sampling_freq=target, features=ds_features)

    def isc(self, col, index="frame", columns="input", method="pearson"):   
        """[summary]

        Args:
            col (str]): Column name to compute the ISC for.
            index (str, optional): Column to be used in computing ISC. Usually this would be the column identifying the time such as the number of the frame. Defaults to "frame".
            columns (str, optional): Column to be used for ISC. Usually this would be the column identifying the video or subject. Defaults to "input".
            method (str, optional): Method to use for correlation pearson, kendall, or spearman. Defaults to "pearson".

        Returns:
            DataFrame: Correlation matrix with index as colmns 
        """                 
        if index == None:
            index = 'frame'
        if columns == None:
            columns = "input"
        mat = pd.pivot_table(self, index = index, columns=columns, values=col).corr(method=method)
        return mat 

    def upsample(self, target, target_type="hz", **kwargs):
        """Upsample Fex columns. Relies on nltools.stats.upsample,
            but ensures that returned object is a Fex object.

        Args:
            target(float): upsampling target, default 'hz' (also 'samples',
                           'seconds')
            kwargs: additional inputs to nltools.stats.upsample

        """
        df_us = upsample(
            self,
            sampling_freq=self.sampling_freq,
            target=target,
            target_type=target_type,
            **kwargs,
        )
        if self.features is not None:
            us_features = upsample(
                self.features,
                sampling_freq=self.sampling_freq,
                target=target,
                target_type=target_type,
                **kwargs,
            )
        else:
            us_features = self.features
        return self.__class__(df_us, sampling_freq=target, features=us_features)

    def distance(self, method="euclidean", **kwargs):
        """Calculate distance between rows within a Fex() instance.

        Args:
            method: type of distance metric (can use any scikit learn or
                    sciypy metric)

        Returns:
            dist: Outputs a 2D distance matrix.

        """
        return Adjacency(
            pairwise_distances(self, metric=method, **kwargs), matrix_type="Distance"
        )

    def rectification(self, std=3):
        """Removes time points when the face position moved
        more than N standard deviations from the mean.

        Args:
            std (default 3): standard deviation from mean to remove outlier face locations
        Returns:
            data: cleaned FEX object

        """
        #### TODO: CHECK IF FACET OR FIND WAY TO DO WITH OTHER ONES TOO #####
        if self.facebox_columns and self.au_columns and self.emotion_columns:
            cleaned = deepcopy(self)
            face_columns = self.facebox_columns
            x_m = self.FaceRectX.mean()
            x_std = self.FaceRectX.std()
            y_m = self.FaceRectY.mean()
            y_std = self.FaceRectY.std()
            x_bool = (self.FaceRectX > std * x_std + x_m) | (
                self.FaceRectX < x_m - std * x_std
            )
            y_bool = (self.FaceRectY > std * y_std + y_m) | (
                self.FaceRectY < y_m - std * y_std
            )
            xy_bool = x_bool | y_bool
            cleaned.loc[
                xy_bool, face_columns + self.au_columns + self.emotion_columns
            ] = np.nan
            return cleaned
        else:
            raise ValueError("Facebox columns need to be defined.")

    def baseline(self, baseline="median", normalize=None, ignore_sessions=False):
        """Reference a Fex object to a baseline.

        Args:
            method: {'median', 'mean', 'begin', FexSeries instance}. Will subtract baseline from Fex object (e.g., mean, median).  If passing a Fex object, it will treat that as the baseline.
            normalize: (str). Can normalize results of baseline. Values can be [None, 'db','pct']; default None.
            ignore_sessions: (bool) If True, will ignore Fex.sessions information. Otherwise, method will be applied separately to each unique session.

        Returns:
            Fex object
        """
        if self.sessions is None or ignore_sessions:
            out = self.copy()
            if type(baseline) == str:
                if baseline == "median":
                    baseline_values = out.median()
                elif baseline == "mean":
                    baseline_values = out.mean()
                elif baseline == "begin":
                    baseline_values = out.iloc[0, :]
                else:
                    raise ValueError(
                        "%s is not implemented please use {mean, median, Fex}"
                        % baseline
                    )
            elif isinstance(baseline, (Series, FexSeries)):
                baseline_values = baseline
            elif isinstance(baseline, (Fex, DataFrame)):
                raise ValueError("Must pass in a FexSeries not a FexSeries Instance.")

            if normalize == "db":
                out = 10 * np.log10(out - baseline_values) / baseline_values
            if normalize == "pct":
                out = 100 * (out - baseline_values) / baseline_values
            else:
                out = out - baseline_values
        else:
            out = self.__class__(sampling_freq=self.sampling_freq)
            for k, v in self.itersessions():
                if type(baseline) == str:
                    if baseline == "median":
                        baseline_values = v.median()
                    elif baseline == "mean":
                        baseline_values = v.mean()
                    elif baseline == "begin":
                        baseline_values = v.iloc[0, :]
                    else:
                        raise ValueError(
                            "%s is not implemented please use {mean, median, Fex}"
                            % baseline
                        )
                elif isinstance(baseline, (Series, FexSeries)):
                    baseline_values = baseline
                elif isinstance(baseline, (Fex, DataFrame)):
                    raise ValueError(
                        "Must pass in a FexSeries not a FexSeries Instance."
                    )

                if normalize == "db":
                    out = out.append(
                        10 * np.log10(v - baseline_values) / baseline_values,
                        session_id=k,
                    )
                if normalize == "pct":
                    out = out.append(
                        100 * (v - baseline_values) / baseline_values, session_id=k
                    )
                else:
                    out = out.append(v - baseline_values, session_id=k)
        return out.__finalize__(self)
        # return self.__class__(out, sampling_freq=self.sampling_freq, features=self.features, sessions=self.sessions)

    def clean(
        self,
        detrend=True,
        standardize=True,
        confounds=None,
        low_pass=None,
        high_pass=None,
        ensure_finite=False,
        ignore_sessions=False,
        *args,
        **kwargs,
    ):
        """Clean Time Series signal

        This function wraps nilearn functionality and can filter, denoise,
        detrend, etc.

        See http://nilearn.github.io/modules/generated/nilearn.signal.clean.html

        This function can do several things on the input signals, in
        the following order:
            - detrend
            - standardize
            - remove confounds
            - low- and high-pass filter

        If Fex.sessions is not None, sessions will be cleaned separately.

        Args:
            confounds: (numpy.ndarray, str or list of Confounds timeseries) Shape must be (instant number, confound number), or just (instant number,). The number of time instants in signals and confounds must be identical (i.e. signals.shape[0] == confounds.shape[0]). If a string is provided, it is assumed to be the name of a csv file containing signals as columns, with an optional one-line header. If a list is provided, all confounds are removed from the input signal, as if all were in the same array.
            low_pass: (float) low pass cutoff frequencies in Hz.
            high_pass: (float) high pass cutoff frequencies in Hz.
            detrend: (bool) If detrending should be applied on timeseries (before confound removal)
            standardize: (bool) If True, returned signals are set to unit variance.
            ensure_finite: (bool) If True, the non-finite values (NANs and infs) found in the data will be replaced by zeros.
            ignore_sessions: (bool) If True, will ignore Fex.sessions information. Otherwise, method will be applied separately to each unique session.

        Returns:
            cleaned Fex instance
        """
        if self.sessions is not None:
            if ignore_sessions:
                sessions = None
            else:
                sessions = self.sessions
        else:
            sessions = None
        return self.__class__(
            pd.DataFrame(
                clean(
                    self.values,
                    detrend=detrend,
                    standardize=standardize,
                    confounds=confounds,
                    low_pass=low_pass,
                    high_pass=high_pass,
                    ensure_finite=ensure_finite,
                    t_r=1.0 / np.float(self.sampling_freq),
                    sessions=sessions,
                    *args,
                    **kwargs,
                ),
                columns=self.columns,
            ),
            sampling_freq=self.sampling_freq,
            features=self.features,
            sessions=self.sessions,
        )

    def decompose(self, algorithm="pca", axis=1, n_components=None, *args, **kwargs):
        """Decompose Fex instance

        Args:
            algorithm: (str) Algorithm to perform decomposition types=['pca','ica','nnmf','fa']
            axis: dimension to decompose [0,1]
            n_components: (int) number of components. If None then retain as many as possible.

        Returns:
            output: a dictionary of decomposition parameters
        """
        out = {}
        out["decomposition_object"] = set_decomposition_algorithm(
            algorithm=algorithm, n_components=n_components, *args, **kwargs
        )
        com_names = ["c%s" % str(x + 1) for x in range(n_components)]
        if axis == 0:
            out["decomposition_object"].fit(self.T)
            out["components"] = self.__class__(
                pd.DataFrame(
                    out["decomposition_object"].transform(self.T),
                    index=self.columns,
                    columns=com_names,
                ),
                sampling_freq=None,
            )
            out["weights"] = self.__class__(
                pd.DataFrame(
                    out["decomposition_object"].components_.T,
                    index=self.index,
                    columns=com_names,
                ),
                sampling_freq=self.sampling_freq,
                features=self.features,
                sessions=self.sessions,
            )
        if axis == 1:
            out["decomposition_object"].fit(self)
            out["components"] = self.__class__(
                pd.DataFrame(
                    out["decomposition_object"].transform(self), columns=com_names
                ),
                sampling_freq=self.sampling_freq,
                features=self.features,
                sessions=self.sessions,
            )
            out["weights"] = self.__class__(
                pd.DataFrame(
                    out["decomposition_object"].components_,
                    index=com_names,
                    columns=self.columns,
                ),
                sampling_freq=None,
            ).T
        return out

    def extract_mean(self, ignore_sessions=False, *args, **kwargs):
        """Extract mean of each feature

        Args:
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            Fex: mean values for each feature
        """
        prefix = "mean_"
        if self.sessions is None or ignore_sessions:
            feats = pd.DataFrame(self.mean()).T
        else:
            feats = pd.DataFrame()
            for k, v in self.itersessions():
                feats = feats.append(pd.Series(v.mean(), name=k))
        feats = self.__class__(feats)
        feats.columns = prefix + feats.columns
        feats = feats.__finalize__(self)
        if ignore_sessions == False:
            feats.sessions = np.unique(self.sessions)
        for attr_name in [
            "au_columns",
            "emotion_columns",
            "facebox_columns",
            "landmark_columns",
            "facepose_columns",
            "gaze_columns",
            "time_columns",
        ]:
            attr_list = feats.__getattr__(attr_name)
            if attr_list:
                new_attr = [prefix + attr for attr in attr_list]
                feats.__setattr__(attr_name, new_attr)
        return feats

    def extract_min(self, ignore_sessions=False, *args, **kwargs):
        """Extract minimum of each feature

        Args:
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.
        
        Returns:
            Fex: (Fex) minimum values for each feature
        """
        prefix = "min_"
        if self.sessions is None or ignore_sessions:
            feats = pd.DataFrame(self.min()).T
        else:
            feats = pd.DataFrame()
            for k, v in self.itersessions():
                feats = feats.append(pd.Series(v.min(), name=k))
        feats = self.__class__(feats)
        feats.columns = prefix + feats.columns
        feats = feats.__finalize__(self)
        if ignore_sessions == False:
            feats.sessions = np.unique(self.sessions)
        for attr_name in [
            "au_columns",
            "emotion_columns",
            "facebox_columns",
            "landmark_columns",
            "facepose_columns",
            "gaze_columns",
            "time_columns",
        ]:
            attr_list = feats.__getattr__(attr_name)
            if attr_list:
                new_attr = [prefix + attr for attr in attr_list]
                feats.__setattr__(attr_name, new_attr)
        return feats

    def extract_max(self, ignore_sessions=False, *args, **kwargs):
        """Extract maximum of each feature

        Args:
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            fex: (Fex) maximum values for each feature
        """
        prefix = "max_"
        if self.sessions is None or ignore_sessions:
            feats = pd.DataFrame(self.max()).T
        else:
            feats = pd.DataFrame()
            for k, v in self.itersessions():
                feats = feats.append(pd.Series(v.max(), name=k))
        feats = self.__class__(feats)
        feats.columns = prefix + feats.columns
        feats = feats.__finalize__(self)
        if ignore_sessions == False:
            feats.sessions = np.unique(self.sessions)
        for attr_name in [
            "au_columns",
            "emotion_columns",
            "facebox_columns",
            "landmark_columns",
            "facepose_columns",
            "gaze_columns",
            "time_columns",
        ]:
            attr_list = feats.__getattr__(attr_name)
            if attr_list:
                new_attr = [prefix + attr for attr in attr_list]
                feats.__setattr__(attr_name, new_attr)
        return feats

    def extract_summary(
        self, mean=True, max=True, min=True, ignore_sessions=False, *args, **kwargs
    ):
        """Extract summary of multiple features

        Args:
            mean: (bool) extract mean of features
            max: (bool) extract max of features
            min: (bool) extract min of features
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            fex: (Fex)
        """
        out = self.__class__().__finalize__(self)
        if ignore_sessions == False:
            out.sessions = np.unique(self.sessions)
        if mean:
            new = self.extract_mean(ignore_sessions=ignore_sessions, *args, **kwargs)
            out = out.append(new, axis=1)
            # for attr_name in ['au_columns', 'emotion_columns', 'facebox_columns', 'landmark_columns', 'facepose_columns', 'gaze_columns', 'time_columns']:
            #     if new.__getattr__(attr_name):
            #         new_attr = new.__getattr__(attr_name)
            #         out.__setattr__(attr_name, new_attr)
        if max:
            new = self.extract_max(ignore_sessions=ignore_sessions, *args, **kwargs)
            out = out.append(new, axis=1)
            # for attr_name in ['au_columns', 'emotion_columns', 'facebox_columns', 'landmark_columns', 'facepose_columns', 'gaze_columns', 'time_columns']:
            #     if out.__getattr__(attr_name) and new.__getattr__(attr_name):
            #         new_attr = out.__getattr__(attr_name) + new.__getattr__(attr_name)
            #         out.__setattr__(attr_name, new_attr)
        if min:
            new = self.extract_min(ignore_sessions=ignore_sessions, *args, **kwargs)
            out = out.append(new, axis=1)
        for attr_name in [
            "au_columns",
            "emotion_columns",
            "facebox_columns",
            "landmark_columns",
            "facepose_columns",
            "gaze_columns",
            "time_columns",
        ]:
            if self.__getattr__(attr_name):
                new_attr = []
                if mean:
                    new_attr.extend(
                        ["mean_" + attr for attr in self.__getattr__(attr_name)]
                    )
                if max:
                    new_attr.extend(
                        ["max_" + attr for attr in self.__getattr__(attr_name)]
                    )
                if min:
                    new_attr.extend(
                        ["min_" + attr for attr in self.__getattr__(attr_name)]
                    )
                out.__setattr__(attr_name, new_attr)
        return out

    def extract_wavelet(self, freq, num_cyc=3, mode="complex", ignore_sessions=False):
        """Perform feature extraction by convolving with a complex morlet wavelet

        Args:
            freq: (float) frequency to extract
            num_cyc: (float) number of cycles for wavelet
            mode: (str) feature to extract, e.g., 'complex','filtered','phase','magnitude','power']
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.
        
        Returns:
            convolved: (Fex instance)

        """
        wav = wavelet(freq, sampling_freq=self.sampling_freq, num_cyc=num_cyc)
        if self.sessions is None or ignore_sessions:
            convolved = self.__class__(
                pd.DataFrame(
                    {x: convolve(y, wav, mode="same") for x, y in self.iteritems()}
                ),
                sampling_freq=self.sampling_freq,
            )
        else:
            convolved = self.__class__(sampling_freq=self.sampling_freq)
            for k, v in self.itersessions():
                session = self.__class__(
                    pd.DataFrame(
                        {x: convolve(y, wav, mode="same") for x, y in v.iteritems()}
                    ),
                    sampling_freq=self.sampling_freq,
                )
                convolved = convolved.append(session, session_id=k)
        if mode == "complex":
            convolved = convolved
        elif mode == "filtered":
            convolved = np.real(convolved)
        elif mode == "phase":
            convolved = np.angle(convolved)
        elif mode == "magnitude":
            convolved = np.abs(convolved)
        elif mode == "power":
            convolved = np.abs(convolved) ** 2
        else:
            raise ValueError(
                "Mode must be ['complex','filtered','phase'," "'magnitude','power']"
            )
        convolved = self.__class__(
            convolved,
            sampling_freq=self.sampling_freq,
            features=self.features,
            sessions=self.sessions,
        )
        convolved.columns = (
            "f" + "%s" % round(freq, 2) + "_" + mode + "_" + self.columns
        )
        return convolved

    def extract_multi_wavelet(
        self, min_freq=0.06, max_freq=0.66, bank=8, *args, **kwargs
    ):
        """Convolve with a bank of morlet wavelets.

        Wavelets are equally spaced from min to max frequency. See extract_wavelet for more information and options.

        Args:
            min_freq: (float) minimum frequency to extract
            max_freq: (float) maximum frequency to extract
            bank: (int) size of wavelet bank
            num_cyc: (float) number of cycles for wavelet
            mode: (str) feature to extract, e.g., ['complex','filtered','phase','magnitude','power']
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            convolved: (Fex instance)
        """
        out = []
        for f in np.geomspace(min_freq, max_freq, bank):
            out.append(self.extract_wavelet(f, *args, **kwargs))
        return self.__class__(
            pd.concat(out, axis=1),
            sampling_freq=self.sampling_freq,
            features=self.features,
            sessions=self.sessions,
        )

    def extract_boft(self, min_freq=0.06, max_freq=0.66, bank=8, *args, **kwargs):
        """Extract Bag of Temporal features

        Args:
            min_freq: maximum frequency of temporal filters
            max_freq: minimum frequency of temporal filters
            bank: number of temporal filter banks, filters are on exponential scale

        Returns:
            wavs: list of Morlet wavelets with corresponding freq
            hzs:  list of hzs for each Morlet wavelet
        """
        # First generate the wavelets
        target_hz = self.sampling_freq
        freqs = np.geomspace(min_freq, max_freq, bank)
        wavs, hzs = [], []
        for i, f in enumerate(freqs):
            wav = np.real(wavelet(f, sampling_freq=target_hz))
            wavs.append(wav)
            hzs.append(str(np.round(freqs[i], 2)))
        wavs = np.array(wavs)[::-1]
        hzs = np.array(hzs)[::-1]
        # # check asymptotes at lowest freq
        # asym = wavs[-1,:10].sum()
        # if asym > .001:
        #     print("Lowest frequency asymptotes at %2.8f " %(wavs[-1,:10].sum()))

        # Convolve data with wavelets
        Feats2Use = self.columns
        feats = pd.DataFrame()
        for feat in Feats2Use:
            _d = self[[feat]].T
            assert _d.isnull().sum().any() == 0, "Data contains NaNs. Cannot convolve. "
            for iw, cm in enumerate(wavs):
                convolved = np.apply_along_axis(
                    lambda m: np.convolve(m, cm, mode="full"), axis=1, arr=_d.values
                )
                # Extract bin features.
                out = pd.DataFrame(convolved.T).apply(calc_hist_auc, args=(None))
                # 6 bins hardcoded from calc_hist_auc
                colnames = [
                    "pos" + str(i) + "_hz_" + hzs[iw] + "_" + feat for i in range(6)
                ]
                colnames.extend(
                    ["neg" + str(i) + "_hz_" + hzs[iw] + "_" + feat for i in range(6)]
                )
                out = out.T
                out.columns = colnames
                feats = pd.concat([feats, out], axis=1)
        return self.__class__(
            feats, sampling_freq=self.sampling_freq, features=self.features
        )

    def calc_pspi(self):
        if self.detector == "FACET":
            pspi_aus = ["AU4", "AU6", "AU7", "AU9", "AU10", "AU43"]
            out = (
                self["AU4"]
                + self[["AU6", "AU7"]].max(axis=1)
                + self[["AU9", "AU10"]].max(axis=1)
                + self["AU43"]
            )
        if self.detector == "OpenFace":
            out = (
                self["AU04_r"]
                + self[["AU06_r", "AU07_r"]].max(axis=1)
                + self[["AU09_r", "AU10_r"]].max(axis=1)
                + self["AU45_r"]
            )
        return out.__finalize__(self)

    def plot_aus(
        self,
        row_n,
        model=None,
        vectorfield=None,
        muscles=None,
        ax=None,
        color="k",
        linewidth=1,
        linestyle="-",
        gaze=None,
        *args,
        **kwargs,
    ):
        if self.detector == "FACET":
            feats = [
                "AU1",
                "AU2",
                "AU4",
                "AU5",
                "AU6",
                "AU7",
                "AU9",
                "AU10",
                "AU12",
                "AU14",
                "AU15",
                "AU17",
                "AU18",
                "AU20",
                "AU23",
                "AU24",
                "AU25",
                "AU26",
                "AU28",
                "AU43",
                "Pitch",
                "Roll",
                "Yaw",
            ]
            if row_n > len(self):
                raise ValueError("Row number out of range.")
            try:
                au = []
                for feat in feats:
                    aun = self[feat]
                    au.append(aun.copy()[row_n])
                au = np.array(au)
                if model is None:
                    model = load_h5("facet.h5")
                if muscles is not None:
                    muscles["facet"] = 1
                ax = plot_face(
                    model=model,
                    au=au,
                    vectorfield=vectorfield,
                    muscles=muscles,
                    ax=ax,
                    color=color,
                    linewidth=linewidth,
                    linestyle=linestyle,
                    gaze=gaze,
                    *args,
                    **kwargs,
                )
                return ax
            except Exception as e:
                print("Unable to plot data:", e)
        if self.detector == "OpenFace":
            feats = [
                "AU01_r",
                "AU02_r",
                "AU04_r",
                "AU05_r",
                "AU06_r",
                "AU07_r",
                "AU09_r",
                "AU10_r",
                "AU12_r",
                "AU14_r",
                "AU15_r",
                "AU17_r",
                "AU20_r",
                "AU23_r",
                "AU25_r",
                "AU26_r",
                "AU45_r",
            ]
            if row_n > len(self):
                raise ValueError("Row number out of range.")
            try:
                au = []
                for feat in feats:
                    aun = self[feat]
                    au.append(aun.copy()[row_n])
                au = np.array(au + [0, 0, 0])

                if gaze:
                    gaze_dat = ["gaze_0_x", "gaze_0_y", "gaze_1_x", "gaze_1_y"]
                    gaze = []
                    for i in range(4):
                        gaze.append(self[gaze_dat[i]][row_n])
                    if gaze_vecs:
                        gaze.append(1)
                    else:
                        gaze.append(0)
                else:
                    gaze = None

                ax = plot_face(
                    model=model,
                    au=au,
                    vectorfield=vectorfield,
                    muscles=muscles,
                    ax=ax,
                    color=color,
                    linewidth=linewidth,
                    linestyle=linestyle,
                    gaze=gaze,
                    *args,
                    **kwargs,
                )
                return ax
            except Exception as e:
                print("Unable to plot data:", e)
        if self.detector == "Affectiva":
            if "AU01" not in self.au_columns:
                feats = [
                    "innerBrowRaise",
                    "browRaise",
                    "browFurrow",
                    "eyeWiden",
                    "cheekRaise",
                    "lidTighten",
                    "noseWrinkle",
                    "upperLipRaise",
                    "smile",
                    "dimpler",
                    "lipCornerDepressor",
                    "chinRaise",
                    "lipStretch",
                    "lipPress",
                    "mouthOpen",
                    "jawDrop",
                    "eyeClosure",
                ]
            else:
                feats = [
                    "AU01",
                    "AU02",
                    "AU04",
                    "AU05",
                    "AU06",
                    "AU07",
                    "AU09",
                    "AU10",
                    "AU12",
                    "AU14",
                    "AU15",
                    "AU17",
                    "AU20",
                    "AU24",
                    "AU25",
                    "AU26",
                    "AU43",
                ]
            if row_n > len(self):
                raise ValueError("Row number out of range.")
            try:
                au = []
                for feat in feats:
                    aun = self[feat]
                    au.append(aun.copy()[row_n] / 20)
                au = np.array(au + [0, 0, 0])
                ax = plot_face(
                    model=model,
                    au=au,
                    vectorfield=vectorfield,
                    muscles=muscles,
                    ax=ax,
                    color=color,
                    linewidth=linewidth,
                    linestyle=linestyle,
                    gaze=gaze,
                    *args,
                    **kwargs,
                )
                return ax
            except Exception as e:
                print("Unable to plot data:", e)

    def plot_detections(self, draw_landmarks=True, draw_facelines=True, muscle=False):
        """Plots detection results by Feat.

        Args:
            draw_landmarks (bool, optional): Whether to draw landmarks. Defaults to True.
            draw_facelines (bool, optional): Whether to draw face lines. Defaults to True.
            muscle (bool, optional): Whether to draw muscle activations. Defaults to False.

        Returns:
            axes: handle to plot
        """

        from PIL import Image
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        import seaborn as sns
        from textwrap import wrap
        sns.set_context("paper", font_scale=2.0)

        # check how many images.
        inputs = self.input().unique()
        all_axes = []
        for imagefile in inputs:
            f, axes = plt.subplots(1, 3, figsize=(15, 7))
            ax = axes[0]
            try:
                if os.path.exists(imagefile):
                    color = "w"
                    # draw base image
                    im = Image.open(imagefile)
                    ax.imshow(im)
                    image_exists = True
                else:
                    image_exists = False
                    color = "k"
            except:
                color = "k"
                print(f"Input image {imagefile} not found.")
                image_exists = False

            sub_data = self.query("input==@imagefile")
            for i in range(len(sub_data)):
                # draw landmarks
                row = sub_data.iloc[[i]]
                landmark = row.landmark().values[0]
                currx = landmark[:68]
                curry = landmark[68:]
                if draw_landmarks:
                    if draw_facelines:
                        draw_lineface(currx, curry, ax=ax, color=color, linewidth=3)
                    else:
                        draw_lineface(currx, curry, ax=ax, color=color, linewidth=0)
                # muscle
                if muscle:
                    au20index = [
                        f"AU{str(i).zfill(2)}"
                        for i in [
                            1,
                            2,
                            4,
                            5,
                            6,
                            7,
                            9,
                            10,
                            12,
                            14,
                            15,
                            17,
                            18,
                            20,
                            23,
                            24,
                            25,
                            26,
                            28,
                            43,
                        ]
                    ]
                    aus = row.aus().T.reindex(index=au20index).fillna(0).T.values[0]
                    draw_muscles(currx, curry, au=aus, ax=ax, all="heatmap")
                # facebox
                facebox = row.facebox().values[0]
                rect = Rectangle(
                    (facebox[0], facebox[1]),
                    facebox[2],
                    facebox[3],
                    linewidth=2,
                    edgecolor="cyan",
                    fill=False,
                )
                ax.add_patch(rect)

            if image_exists:
                if sub_data.input().any():
                    ax.set_title(
                        "\n".join(wrap(sub_data.input().unique()[0], 30)), loc="left", wrap=True, fontsize=14
                    )
            else:
                ax.set_title("\n".join(wrap(imagefile, 30)), loc="left", wrap=True, fontsize=14)
                ax.set(ylim=ax.get_ylim()[::-1])
                ax.set_aspect("equal", "box")

            # plot AUs
            sub_data.aus().T.plot(kind="barh", ax=axes[1])
            axes[1].invert_yaxis()
            axes[1].get_legend().remove()
            axes[1].set(xlim=[0, 1.1], title="Action Units")

            # plot emotions
            sub_data.emotions().T.plot(kind="barh", ax=axes[2])
            axes[2].invert_yaxis()
            axes[2].get_legend().remove()
            axes[2].set(xlim=[0, 1.1], title="Emotions")

            plt.tight_layout()
            plt.show()
            all_axes.append(axes)
        return axes


class Fextractor:
    """
    Fextractor is a class that extracts and merges features from a Fex instance
    in preparation for data analysis.
    """

    def __init__(self):
        self.extracted_features = []

    def mean(self, fex_object, ignore_sessions=False, *args, **kwargs):
        """Extract mean of each feature

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            Fex: mean values for each feature
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_mean(ignore_sessions, *args, **kwargs)
        )

    def max(self, fex_object, ignore_sessions=False, *args, **kwargs):
        """Extract maximum of each feature

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            Fex: (Fex) maximum values for each feature
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_max(ignore_sessions, *args, **kwargs)
        )

    def min(self, fex_object, ignore_sessions=False, *args, **kwargs):
        """Extract minimum of each feature

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            Fex: (Fex) minimum values for each feature
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_min(ignore_sessions, *args, **kwargs)
        )

    def summary(
        self,
        fex_object,
        mean=False,
        max=False,
        min=False,
        ignore_sessions=False,
        *args,
        **kwargs,
    ):
        """Extract summary of multiple features
        Args:
            fex_object: (Fex) Fex instance to extract features from.
            mean: (bool) extract mean of features
            max: (bool) extract max of features
            min: (bool) extract min of features
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.
       
        Returns:
            fex: (Fex)
        """
        self.extracted_features.append(
            fex_object.extract_summary(mean, max, min, ignore_sessions, *args, **kwargs)
        )

    def wavelet(
        self, fex_object, freq, num_cyc=3, mode="complex", ignore_sessions=False
    ):
        """Perform feature extraction by convolving with a complex morlet
        wavelet

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            freq: (float) frequency to extract
            num_cyc: (float) number of cycles for wavelet
            mode: (str) feature to extract, e.g., ['complex','filtered','phase','magnitude','power']
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            convolved: (Fex instance)
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_wavelet(freq, num_cyc, mode, ignore_sessions)
        )

    def multi_wavelet(
        self, fex_object, min_freq=0.06, max_freq=0.66, bank=8, *args, **kwargs
    ):
        """Convolve with a bank of morlet wavelets.
        
        Wavelets are equally spaced from min to max frequency. See extract_wavelet for more information and options.

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            min_freq: (float) minimum frequency to extract
            max_freq: (float) maximum frequency to extract
            bank: (int) size of wavelet bank
            num_cyc: (float) number of cycles for wavelet
            mode: (str) feature to extract, e.g., ['complex','filtered','phase','magnitude','power']
            ignore_sessions: (bool) ignore sessions or extract separately by sessions if available.

        Returns:
            convolved: (Fex instance)
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_multi_wavelet(min_freq, max_freq, bank, *args, **kwargs)
        )

    def boft(self, fex_object, min_freq=0.06, max_freq=0.66, bank=8, *args, **kwargs):
        """Extract Bag of Temporal features

        Args:
            fex_object: (Fex) Fex instance to extract features from.
            min_freq: maximum frequency of temporal filters
            max_freq: minimum frequency of temporal filters
            bank: number of temporal filter banks, filters are on exponential scale

        Returns:
            wavs: list of Morlet wavelets with corresponding freq
            hzs:  list of hzs for each Morlet wavelet
        """
        if not isinstance(fex_object, (Fex, DataFrame)):
            raise ValueError("Must pass in a Fex object.")
        self.extracted_features.append(
            fex_object.extract_boft(min_freq, max_freq, bank, *args, **kwargs)
        )

    def merge(self, out_format="long"):
        """Merge all extracted features to a single dataframe
        
        Args:
            format: (str) Output format of merged data. Can be set to 'long' or 'wide'. Defaults to long.
        
        Returns:
            merged: (DataFrame) DataFrame containing merged features extracted from a Fex instance.
        """
        out = reduce(
            lambda x, y: pd.merge(x, y, left_index=True, right_index=True),
            self.extracted_features,
        )
        out["sessions"] = out.index

        if out_format == "long":
            out = out.melt(id_vars="sessions")
        elif out_format == "wide":
            pass
        return out
